from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.entities import Request, ReviewItem
from app.services.tools.registry import SafeToolRegistry


class ReviewConflictError(ValueError):
    pass


class ReviewDecisionError(RuntimeError):
    """A claimed review failed safely and may be retried."""


IN_PROGRESS_STATUSES = (
    "approval_in_progress",
    "rejection_in_progress",
    "edit_approval_in_progress",
)


class ReviewService:
    def __init__(self, tools: SafeToolRegistry, *, claim_timeout_seconds: int = 300) -> None:
        self.tools = tools
        self.claim_timeout_seconds = claim_timeout_seconds

    def approve(self, db: Session, review: ReviewItem, notes: str | None = None) -> ReviewItem:
        claimed_status = "approval_in_progress"
        self._claim(db, review, claimed_status, action="approve")
        try:
            executed = self.tools.execute_pending_for_request(db, review.request_id)
            request = self._request(db, review.request_id)
            if executed:
                results = "; ".join(
                    f"{call.tool_name}: {json.dumps(call.result_json, ensure_ascii=False)}"
                    for call in executed
                )
                request.response_text = (
                    f"{request.response_text or ''}\n\nApproved tool result: {results}".strip()
                )
            review.status = "approved"
            review.reviewer_notes = notes
            review.resolved_at = utcnow()
            request.status = "completed"
            request.requires_review = False
            request.completed_at = utcnow()
            return self._complete(db, review, action="approve")
        except Exception as exc:
            self._mark_failed(db, review.id, claimed_status, action="approve", error=exc)
            raise ReviewDecisionError("review approval failed safely; retry is allowed") from exc

    def reject(self, db: Session, review: ReviewItem, notes: str | None = None) -> ReviewItem:
        claimed_status = "rejection_in_progress"
        self._claim(db, review, claimed_status, action="reject")
        try:
            request = self._request(db, review.request_id)
            review.status = "rejected"
            review.reviewer_notes = notes
            review.resolved_at = utcnow()
            request.status = "rejected"
            request.requires_review = False
            request.completed_at = utcnow()
            return self._complete(db, review, action="reject")
        except Exception as exc:
            self._mark_failed(db, review.id, claimed_status, action="reject", error=exc)
            raise ReviewDecisionError("review rejection failed safely; retry is allowed") from exc

    def edit_and_approve(
        self,
        db: Session,
        review: ReviewItem,
        edited_response: str,
        notes: str | None = None,
    ) -> ReviewItem:
        claimed_status = "edit_approval_in_progress"
        self._claim(db, review, claimed_status, action="edit_and_approve")
        try:
            self.tools.execute_pending_for_request(db, review.request_id)
            request = self._request(db, review.request_id)
            review.status = "edited_and_approved"
            review.reviewer_notes = notes
            review.edited_response = edited_response
            review.resolved_at = utcnow()
            request.response_text = edited_response
            request.status = "completed"
            request.requires_review = False
            request.completed_at = utcnow()
            return self._complete(db, review, action="edit_and_approve")
        except Exception as exc:
            self._mark_failed(
                db,
                review.id,
                claimed_status,
                action="edit_and_approve",
                error=exc,
            )
            raise ReviewDecisionError("review edit approval failed safely; retry is allowed") from exc

    def _claim(
        self,
        db: Session,
        review: ReviewItem,
        claimed_status: str,
        *,
        action: str,
    ) -> None:
        now = utcnow()
        stale_before = now - timedelta(seconds=self.claim_timeout_seconds)
        claimable = or_(
            ReviewItem.status.in_(("pending", "decision_failed")),
            and_(
                ReviewItem.status.in_(IN_PROGRESS_STATUSES),
                ReviewItem.decision_started_at.is_not(None),
                ReviewItem.decision_started_at <= stale_before,
            ),
        )
        result = db.execute(
            update(ReviewItem)
            .where(ReviewItem.id == review.id, claimable)
            .values(
                status=claimed_status,
                decision_started_at=now,
                decision_error=None,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise ReviewConflictError("review item is resolved or actively claimed")
        # Commit the lease before executing a pending side effect. A concurrent
        # reviewer observes the active claim and receives 409.
        db.commit()
        db.refresh(review)
        self._append_history(
            review,
            {
                "event": "claimed",
                "action": action,
                "status": claimed_status,
                "at": now.isoformat(),
            },
        )
        db.commit()
        db.refresh(review)

    @staticmethod
    def _complete(db: Session, review: ReviewItem, *, action: str) -> ReviewItem:
        ReviewService._append_history(
            review,
            {
                "event": "completed",
                "action": action,
                "status": review.status,
                "at": utcnow().isoformat(),
            },
        )
        review.decision_started_at = None
        review.decision_error = None
        db.commit()
        db.refresh(review)
        return review

    @staticmethod
    def _mark_failed(
        db: Session,
        review_id: str,
        claimed_status: str,
        *,
        action: str,
        error: Exception,
    ) -> None:
        db.rollback()
        stored = db.scalar(select(ReviewItem).where(ReviewItem.id == review_id))
        if stored is None or stored.status != claimed_status:
            return
        safe_error = f"{type(error).__name__}: decision processing failed"
        stored.status = "decision_failed"
        stored.decision_error = safe_error
        ReviewService._append_history(
            stored,
            {
                "event": "failed",
                "action": action,
                "status": "decision_failed",
                "error_type": type(error).__name__,
                "at": utcnow().isoformat(),
            },
        )
        db.commit()

    @staticmethod
    def _append_history(review: ReviewItem, event: dict[str, str]) -> None:
        review.decision_history_json = [*(review.decision_history_json or []), event]

    @staticmethod
    def _request(db: Session, request_id: str) -> Request:
        request = db.scalar(select(Request).where(Request.id == request_id))
        if request is None:  # pragma: no cover - protected by FK
            raise LookupError("request not found")
        return request
