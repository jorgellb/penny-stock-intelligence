"""Scheduler entrypoint: python -m app.jobs.scheduler."""

from app.jobs import run_scheduler

if __name__ == "__main__":
    run_scheduler()
