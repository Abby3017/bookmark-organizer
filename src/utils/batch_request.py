# Batches will be completed within 24h, but may be processed sooner depending on global usage.
from utils.colors import ok, warn


async def upload_batch_file(client: object, file_path: str):
    batch_file = await client.files.create(
        file=open(file_path, "rb"),
        purpose="batch"
    )
    return batch_file


async def create_batch_job(batch_file_id: str, client: object):
    batch_job = await client.batches.create(
        input_file_id=batch_file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )
    return batch_job


async def retrieve_batch_job(batch_job_id: str, client: object):
    """Retrieve the current status of a batch job from OpenAI."""
    return await client.batches.retrieve(batch_job_id)


async def download_batch_file(file_id: str, client: object, file_name: str):
    """Download a file (output or error) associated with a batch job."""
    response = await client.files.content(file_id)
    content = response.read()
    with open(file_name, 'wb') as file:
        file.write(content)
        print(ok("File downloaded: {}".format(file_name)))
