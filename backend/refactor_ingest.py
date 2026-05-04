import re

with open("app/tasks/import_tasks.py", "r", encoding="utf-8") as f:
    code = f.read()

# Remove Celery decorators and self parameter
code = re.sub(r"@celery_app\.task[^\n]*\n", "", code)
code = code.replace("def run_gmail_import(self, job_id: str, user_id: int) -> dict:", "def run_gmail_import(job_id: str, user_id: int) -> dict:")

# Remove celery import
code = code.replace("from app.celery_app import celery_app\n", "")

# Remove self.retry
code = code.replace("raise self.retry(exc=exc, countdown=60)", "pass # Removed retry")

# Add console print
print_code = """
            if parse_result.status == MessageStatus.ACCEPTED:
                new_segs = build_segments_and_trips(db, user_id, parse_result.flights)
                job.segment_count += new_segs
                print(f"[JOB {job_id}] FOUND FLIGHT! Total flights: {job.segment_count}")

            db.commit()

            # Periodic progress flush every 10 messages
            if job.scanned_count % 10 == 0:
                print(f"[JOB {job_id}] Progress -> Scanned: {job.scanned_count} | Parsed: {job.parsed_count} | Flights: {job.segment_count}")
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
"""
code = re.sub(r"            if parse_result\.status == MessageStatus\.ACCEPTED:.*?(?=        job\.state = \"completed\")", print_code, code, flags=re.DOTALL)

with open("app/tasks/import_tasks.py", "w", encoding="utf-8") as f:
    f.write(code)


with open("app/routers/ingest.py", "r", encoding="utf-8") as f:
    code2 = f.read()

code2 = code2.replace("from fastapi import APIRouter, Depends, HTTPException, status", "from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks")

code2 = code2.replace("def start_gmail_import(\n    current_user: User = Depends(get_current_user),", "def start_gmail_import(\n    background_tasks: BackgroundTasks,\n    current_user: User = Depends(get_current_user),")

code2 = code2.replace("run_gmail_import.delay(job_id=job_id, user_id=current_user.id)", "background_tasks.add_task(run_gmail_import, job_id=job_id, user_id=current_user.id)")

with open("app/routers/ingest.py", "w", encoding="utf-8") as f:
    f.write(code2)

print("Done")
