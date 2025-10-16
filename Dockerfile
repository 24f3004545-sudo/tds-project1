# Use a Python base image
FROM python:3.9

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user (a required security practice for Hugging Face)
RUN useradd -m -u 1000 user
USER user

# Copy the rest of your application code (including main.py)
# Note: The . after the COPY command refers to the current directory
COPY --chown=user . .

# Command to run your FastAPI application using uvicorn on port 7860
# 'main' is the file (main.py), 'app' is the FastAPI object name (app = FastAPI())
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
