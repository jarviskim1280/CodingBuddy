"""Code review agent — reviews PRs and leaves structured feedback."""
import json
from pathlib import Path
from typing import Optional

from buddy.agents.base import BaseAgent
from buddy.config import settings
from buddy.db.models import PRReview, Task
from buddy.db.ops import SessionLocal, create_review, update_review, latest_review


REVIEW_TOOLS = [
    {
        "name": "submit_review",
        "description": "Submit a structured code review for the PR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": ["approved", "changes_requested"],
                    "description": "Approval decision",
                },
                "summary": {"type": "string", "description": "High-level review summary"},
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "line": {"type": "integer"},
                            "issue": {"type": "string"},
                            "suggestion": {"type": "string"},
                        },
                        "required": ["file", "issue"],
                    },
                    "description": "Specific issues found (empty if approved)",
                },
            },
            "required": ["verdict", "summary", "comments"],
        },
    },
]

REVIEW_SYSTEM = """You are an expert code reviewer. Your job is to review pull requests
and provide actionable, constructive feedback.

Focus on:
- Correctness: does the code do what it's supposed to?
- Security: obvious vulnerabilities (SQL injection, auth bypasses, etc.)
- Error handling: unhandled exceptions, missing validation
- Code quality: readability, naming, obvious duplication
- Tests: are there any, do they cover the important paths?

Be concise. Approve if the code is reasonable and works — don't nitpick style.
Always call `submit_review` with your verdict.
"""


class ReviewerAgent(BaseAgent):
    agent_type = "reviewer"

    def build_system_prompt(self, task: Task, stack: dict) -> str:
        return REVIEW_SYSTEM

    def build_user_prompt(self, task: Task, stack: dict, extra_context: str = "") -> str:
        return f"Review the PR for task: {task.description}\n\n{extra_context}"

    async def review_pr(
        self,
        task: Task,
        diff: str,
        round_number: int,
        previous_comments: Optional[list] = None,
    ) -> PRReview:
        """Run Claude review on a diff, store result in DB."""
        with SessionLocal() as session:
            review = create_review(session, task.id, task.pr_url, round_number)
            review_id = review.id

        context = f"PR DIFF:\n```\n{diff}\n```"
        if previous_comments:
            ctx_prev = json.dumps(previous_comments, indent=2)
            context += f"\n\nPREVIOUS REVIEW COMMENTS (round {round_number - 1}):\n{ctx_prev}\n\nPlease check if these were addressed."

        messages = [
            {"role": "user", "content": f"Review this pull request for task: {task.description}\n\n{context}"}
        ]

        response = await self.client.messages.create(
            model=settings.claude_model,
            max_tokens=4096,
            system=REVIEW_SYSTEM,
            tools=REVIEW_TOOLS,
            tool_choice={"type": "any"},
            messages=messages,
        )

        verdict = "changes_requested"
        summary = ""
        comments: list = []

        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_review":
                verdict = block.input.get("verdict", "changes_requested")
                summary = block.input.get("summary", "")
                comments = block.input.get("comments", [])
                break

        self.log(f"Review round {round_number}: {verdict} — {summary}")

        with SessionLocal() as session:
            update_review(
                session,
                review_id,
                status=verdict,
                comments=comments,
            )
            review = session.get(PRReview, review_id)
            # detach
            session.expunge(review)

        return review

    async def do_address_comments(
        self,
        task: Task,
        repo_path: Path,
        stack: dict,
        comments: list,
    ) -> str:
        """Worker-side: given review comments, fix the code."""
        comments_text = json.dumps(comments, indent=2)
        system = self.build_system_prompt(task, stack)
        prompt = f"""You are addressing code review feedback for task: {task.description}

REVIEW COMMENTS TO ADDRESS:
{comments_text}

Instructions:
1. Call `list_files` on "." to see existing code.
2. Read the relevant files.
3. Fix each issue mentioned in the review comments.
4. Call `finish` when all comments have been addressed.
"""
        return await self.run_tool_loop(repo_path, system, prompt)
