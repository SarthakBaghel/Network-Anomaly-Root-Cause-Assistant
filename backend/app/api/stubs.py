from fastapi import HTTPException


def feature_not_implemented(owner: str) -> None:
    raise HTTPException(
        status_code=501,
        detail={
            "error": {
                "code": "FEATURE_NOT_IMPLEMENTED",
                "message": f"Milestone-0 contract stub; implementation owner is {owner}.",
                "details": [],
            }
        },
    )

