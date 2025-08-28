1. Enable required services:
   gcloud services enable run.googleapis.com aiplatform.googleapis.com

2. Submit your container image:
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/llm-runner

3. Deploy to Cloud Run:
   gcloud run deploy llm-runner \
     --image gcr.io/YOUR_PROJECT_ID/llm-runner \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated