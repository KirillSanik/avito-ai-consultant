from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import AssignmentReviewer, Submission, User


def display_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.login


def _linked_reviewers(assignment_id: int, db: Session) -> list[AssignmentReviewer]:
    return list(
        db.scalars(
            select(AssignmentReviewer)
            .where(
                AssignmentReviewer.assignment_id == assignment_id,
                AssignmentReviewer.user_id.is_not(None),
            )
            .options(selectinload(AssignmentReviewer.user))
            .order_by(AssignmentReviewer.id)
        ).all()
    )


def _assignment_submissions(assignment_id: int, db: Session) -> list[Submission]:
    return list(
        db.scalars(
            select(Submission)
            .where(Submission.assignment_id == assignment_id)
            .order_by(Submission.id)
        ).all()
    )


def recount_reviewer_stats(assignment_id: int, db: Session) -> None:
    reviewers = list(
        db.scalars(
            select(AssignmentReviewer)
            .where(AssignmentReviewer.assignment_id == assignment_id)
            .order_by(AssignmentReviewer.id)
        ).all()
    )
    submissions = _assignment_submissions(assignment_id, db)
    for reviewer in reviewers:
        if reviewer.user_id is not None:
            assigned = [
                item
                for item in submissions
                if item.reviewer_user_id == reviewer.user_id
            ]
        else:
            assigned = [
                item
                for item in submissions
                if item.reviewer_user_id is None and item.reviewer == reviewer.name
            ]
        reviewer.total = len(assigned)
        reviewer.checked = sum(item.status == "reviewed" for item in assigned)
        reviewer.anomaly = False


def assign_new_submission(submission: Submission, assignment_id: int, db: Session) -> None:
    reviewers = _linked_reviewers(assignment_id, db)
    if not reviewers:
        submission.reviewer_user_id = None
        submission.reviewer = None
        recount_reviewer_stats(assignment_id, db)
        return
    loads = {item.user_id: 0 for item in reviewers}
    for existing in _assignment_submissions(assignment_id, db):
        if existing.id == submission.id:
            continue
        if existing.reviewer_user_id in loads:
            loads[existing.reviewer_user_id] += 1
    reviewer = min(reviewers, key=lambda item: (loads[item.user_id], item.id))
    assert reviewer.user_id is not None and reviewer.user is not None
    submission.reviewer_user_id = reviewer.user_id
    submission.reviewer = display_name(reviewer.user)
    recount_reviewer_stats(assignment_id, db)


def rebalance_assignment_submissions(assignment_id: int, db: Session) -> None:
    reviewers = _linked_reviewers(assignment_id, db)
    submissions = _assignment_submissions(assignment_id, db)
    reviewer_by_user = {
        item.user_id: item for item in reviewers if item.user_id is not None
    }
    totals = {user_id: 0 for user_id in reviewer_by_user}

    for submission in submissions:
        if (
            submission.status == "reviewed"
            and submission.reviewer_user_id in reviewer_by_user
        ):
            totals[submission.reviewer_user_id] += 1

    pending = [item for item in submissions if item.status != "reviewed"]
    if not reviewers:
        for submission in pending:
            submission.reviewer_user_id = None
            submission.reviewer = None
    else:
        for submission in pending:
            reviewer = min(
                reviewers,
                key=lambda item: (totals[item.user_id], item.id),
            )
            assert reviewer.user_id is not None and reviewer.user is not None
            submission.reviewer_user_id = reviewer.user_id
            submission.reviewer = display_name(reviewer.user)
            totals[reviewer.user_id] += 1

    recount_reviewer_stats(assignment_id, db)


def backfill_reviewer_user_ids(db: Session) -> None:
    reviewers = list(
        db.scalars(
            select(AssignmentReviewer)
            .where(AssignmentReviewer.user_id.is_(None))
            .order_by(AssignmentReviewer.id)
        ).all()
    )
    users = list(db.scalars(select(User)).all())
    by_telegram = {user.telegram: user for user in users if user.telegram}
    by_name = {display_name(user): user for user in users}
    for reviewer in reviewers:
        user = by_telegram.get(reviewer.telegram) or by_name.get(reviewer.name)
        if user is not None:
            reviewer.user_id = user.id

    submissions = list(
        db.scalars(
            select(Submission).where(
                Submission.reviewer_user_id.is_(None),
                Submission.reviewer.is_not(None),
            )
        ).all()
    )
    for submission in submissions:
        user = by_name.get(submission.reviewer or "")
        if user is not None:
            submission.reviewer_user_id = user.id

    assignment_ids = set(
        db.scalars(select(AssignmentReviewer.assignment_id).distinct()).all()
    )
    for assignment_id in assignment_ids:
        rebalance_assignment_submissions(assignment_id, db)
    db.commit()
