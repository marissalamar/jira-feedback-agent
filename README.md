# Jira Community Intelligence Agent

A live AI agent that monitors the Atlassian Jira community forum, 
classifies customer feedback at scale, and generates executive-level 
product intelligence. Updated automatically on a daily schedule.

## Live Demo
🔗 [jira-feedback-agent.onrender.com](https://jira-feedback-agent.onrender.com)

## What It Does
- Scrapes all Jira community posts from the trailing 90 days (~1,800+ posts)
- Uses Claude AI to classify each post by theme, sentiment, and severity
- Clusters feedback into recurring themes automatically
- Generates an AI-written executive summary with top pain points and recommended actions
- Displays everything in a live dashboard built for a product leadership audience
- Runs on an automated daily schedule — no manual intervention needed

## Why I Built This
Product ops teams spend significant time manually monitoring community 
feedback, sampling posts, and synthesizing patterns. This agent automates 
that entire workflow, from data collection to executive brief, 
demonstrating how agentic AI can augment product operations work at scale.

## Tech Stack
- **AI:** Claude (Anthropic API)
- **Scraping:** BeautifulSoup + Requests
- **Dashboard:** Streamlit
- **Hosting:** Render
- **Data:** Atlassian Jira community forum (public)

## Built By
Marissa LaMar — Product Operations
[LinkedIn](https://www.linkedin.com/in/marissa-lamar/)
