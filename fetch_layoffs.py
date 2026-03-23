"""
fetch_layoffs.py
----------------
Downloads the Layoffs.fyi dataset and uploads it to S3.

What Layoffs.fyi is:
    A crowd-sourced database of tech layoffs since 2022.
    Columns include: company, location, industry, total_laid_off,
    percentage_laid_off, date, stage, country, funds_raised_millions.

What this script does:
    1. Downloads the CSV from Layoffs.fyi's public GitHub mirror
    2. Validates the columns are what we expect
    3. Adds an 'ingested_at' timestamp so we know when we pulled it
    4. Uploads the raw CSV to S3 raw/layoffs/
    5. Logs every step so we can debug if something goes wrong

Run this script: python ingestion/fetch_layoffs.py
"""

import os
import io
import logging
from datetime import datetime, timezone

import boto3
import pandas as pd
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
# This is how Python reads your AWS keys and bucket name
# without hardcoding them in the script
load_dotenv()

# Set up logging — prints timestamped messages to terminal
# so you can see exactly what's happening at each step
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --- Constants ---
# The public Layoffs.fyi dataset is mirrored on GitHub
# This URL gives you the raw CSV file directly
LAYOFFS_URL = (
    "https://raw.githubusercontent.com/datasets/layoffs/main/data/layoffs.csv"
)

# Fallback URL if the above changes — Kaggle public dataset
LAYOFFS_FALLBACK_URL = (
    "https://raw.githubusercontent.com/fares-ds/layoffs-fyi/main/layoffs.csv"
)

# These are the columns we expect in the dataset
# If the download returns different columns, we want to know immediately
EXPECTED_COLUMNS = {
    "company", "location", "industry", "total_laid_off",
    "percentage_laid_off", "date", "stage", "country", "funds_raised_millions"
}

# S3 config — reads from your .env file
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
S3_KEY = f"raw/layoffs/layoffs_{datetime.now().strftime('%Y-%m-%d')}.csv"


def fetch_layoffs_csv(url: str, timeout: int = 30) -> pd.DataFrame:
    """
    Downloads the Layoffs.fyi CSV from a URL and returns it as a DataFrame.

    Why we use requests instead of pd.read_csv(url) directly:
        requests gives us control over timeout, retry logic, and error handling.
        pd.read_csv(url) can hang forever if the network is slow.
    """
    logger.info(f"Downloading Layoffs.fyi data from: {url}")

    response = requests.get(url, timeout=timeout)

    # raise_for_status() throws an exception if the HTTP status is 4xx or 5xx
    # This is a best practice — fail loudly rather than silently saving
    # an empty or error HTML page as if it were real data
    response.raise_for_status()

    # io.StringIO converts the response text into a file-like object
    # that pd.read_csv can read — without saving to disk first
    df = pd.read_csv(io.StringIO(response.text))

    logger.info(f"Downloaded {len(df):,} rows, {len(df.columns)} columns")
    return df


def validate_columns(df: pd.DataFrame) -> None:
    """
    Checks that the downloaded CSV has the columns we expect.

    Why this matters:
        Layoffs.fyi could change their schema at any time.
        If a column disappears, our SQL queries will break silently.
        Better to catch it here and fail loudly.
    """
    actual_columns = set(df.columns.str.lower().str.strip())
    missing = EXPECTED_COLUMNS - actual_columns

    if missing:
        raise ValueError(
            f"Downloaded CSV is missing expected columns: {missing}. "
            f"Actual columns: {actual_columns}. "
            f"Schema may have changed — check {LAYOFFS_URL}"
        )

    logger.info("Column validation passed — all expected columns present")


def clean_layoffs(df: pd.DataFrame) -> pd.DataFrame:
    """
    Light cleaning on the raw data before uploading to S3.

    Why we keep this minimal at this stage:
        The raw/ folder in S3 should be as close to the original as possible.
        Heavy transformation happens in the Glue ETL job (Day 2).
        This just makes the data safe to work with.
    """
    # Standardize column names: lowercase + strip whitespace
    df.columns = df.columns.str.lower().str.strip()

    # Parse the date column to a standard format
    # errors='coerce' turns unparseable dates into NaT (null) instead of crashing
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Add ingestion timestamp — critical for tracking when data was pulled
    # timezone.utc makes it timezone-aware (best practice)
    df["ingested_at"] = datetime.now(timezone.utc).isoformat()

    # Strip whitespace from string columns
    string_cols = df.select_dtypes(include="object").columns
    df[string_cols] = df[string_cols].apply(lambda x: x.str.strip())

    logger.info(f"Cleaned data: {len(df):,} rows remaining")
    return df


def upload_to_s3(df: pd.DataFrame, bucket: str, key: str) -> None:
    """
    Uploads the DataFrame as a CSV file to S3.

    Why we upload to S3 instead of saving locally:
        S3 is the data lake. Everything flows through it.
        Lambda, Glue, and Athena all read from S3 — not your local machine.
        This is how real data pipelines work in production.
    """
    # boto3 is the AWS SDK for Python
    # It automatically uses the credentials from your .env / AWS CLI config
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION", "us-east-1")
    )

    # Convert DataFrame to CSV string in memory (no disk write)
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    logger.info(f"Uploading to s3://{bucket}/{key}")

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_buffer.getvalue().encode("utf-8"),
        ContentType="text/csv"
    )

    logger.info(f"Upload complete: s3://{bucket}/{key}")
    logger.info(f"File size: {len(csv_buffer.getvalue()) / 1024:.1f} KB")


def main():
    """
    Orchestrates the full ingestion flow:
    download → validate → clean → upload to S3
    """
    logger.info("=== Layoffs.fyi ingestion started ===")

    # Step 1: Try primary URL, fall back to secondary if it fails
    try:
        df = fetch_layoffs_csv(LAYOFFS_URL)
    except Exception as e:
        logger.warning(f"Primary URL failed: {e}. Trying fallback...")
        df = fetch_layoffs_csv(LAYOFFS_FALLBACK_URL)

    # Step 2: Validate columns
    validate_columns(df)

    # Step 3: Light cleaning
    df = clean_layoffs(df)

    # Step 4: Upload to S3
    if not S3_BUCKET:
        raise EnvironmentError(
            "S3_BUCKET_NAME not set in .env file. "
            "Did you copy .env.example to .env and fill in your values?"
        )

    upload_to_s3(df, S3_BUCKET, S3_KEY)

    logger.info("=== Layoffs.fyi ingestion complete ===")
    logger.info(f"Rows ingested: {len(df):,}")
    logger.info(f"S3 location: s3://{S3_BUCKET}/{S3_KEY}")


if __name__ == "__main__":
    main()
