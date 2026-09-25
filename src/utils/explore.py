
# if we have multiple pending batch jobs, we can loop through all of them and check their status and
# download the results


async def download_processed_batches():
    rows = get_all_batches_with_status(status='pending')
    if not rows:
        print(warn("No pending batch jobs found."))
        return

    print(info(f"Found {len(rows)} pending batch job(s)."))

    for row in rows:
        job_id = row['job_id']
        print(info(f"Checking status for batch job: {job_id}"))

        # Retrieve the current batch status from OpenAI
        batch_job = await retrieve_batch_job(job_id, CLIENT)
        status = batch_job.status

        if status == 'completed':
            # Download the output file and update DB status to 'completed'
            output_file_id = batch_job.output_file_id
            file_path = "./data/processed/{}.jsonl".format(job_id)
            await download_batch_file(output_file_id, CLIENT, file_path)
            update_batch_job_status(
                job_id, status='completed', file_path_write=file_path)
            print(
                ok(f"Batch job {job_id} completed. Results saved to {file_path}"))

        elif status in ('failed', 'expired', 'cancelled'):
            # Download the error log and update DB status to 'failed'
            error_file_id = getattr(batch_job, 'error_file_id', None)
            if error_file_id:
                error_path = "./data/processed/{}_errors.jsonl".format(job_id)
                await download_batch_file(error_file_id, CLIENT, error_path)
                print(warn(f"Error log saved to {error_path}"))
            else:
                print(warn(f"No error file available for batch job {job_id}"))
            update_batch_job_status(job_id, status='failed')
            print(
                warn(f"Batch job {job_id} marked as failed (OpenAI status: {status})."))

        else:
            # Job is still in progress (validating, in_progress, finalizing)
            print(
                info(f"Batch job {job_id} is still '{status}'. Try again later."))

    print(ok("Finished checking all pending batch jobs."))