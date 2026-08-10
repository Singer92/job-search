import json
import os
import re

import yaml
from openai import OpenAI


def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_json_loose(text):
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()

    start = text.find("{")
    end = text.rfind("}") + 1

    if start >= 0 and end > start:
        text = text[start:end]

    return json.loads(text)


def call_llm_json(prompt):
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add your Gemini key as OPENAI_API_KEY in GitHub Secrets.")

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )

    model = os.getenv("OPENAI_MODEL", "gemini-2.0-flash")

    messages = [
        {
            "role": "system",
            "content": "You are a precise job-matching engine. Return only valid JSON.",
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
        )

    return parse_json_loose(response.choices[0].message.content)


def build_prompt(job, cfg, min_score):
    candidate = cfg.get("candidate", {})
    preferences = cfg.get("preferences", {})

    job_copy = dict(job)
    max_chars = cfg.get("agent", {}).get("max_description_chars", 6000)
    job_copy["description"] = (job_copy.get("description") or "")[:max_chars]

    return f"""
You are a global job-search agent for Ezhilarasi Murugesan.

CANDIDATE PROFILE:
{json.dumps(candidate, indent=2, ensure_ascii=False)}

SEARCH PREFERENCES:
{json.dumps(preferences, indent=2, ensure_ascii=False)}

JOB:
{json.dumps(job_copy, indent=2, ensure_ascii=False)}

TASK:
Evaluate how well this job matches the candidate.

RULES:
1. Prioritise Carnatic music, Indian classical music, vocal pedagogy, music education, curriculum design, online music teaching, ethnomusicology, teaching artist, and composer/vocalist roles.
2. The candidate is open to remote work, India roles, and relocation.
3. For roles requiring relocation outside India, only consider them strong if the job description explicitly mentions visa sponsorship, work permit support, relocation support, or international hiring. If no such evidence exists, set visa_sponsorship_evidence to "no" or "unclear" and keep match_score at or below 60.
4. For India-based or remote roles, visa sponsorship is not required.
5. Do not invent requirements or benefits.
6. If the role is clearly irrelevant, give a low score.
7. Write a concise tailored cover letter only if match_score is likely at least {min_score}; otherwise return an empty string.

RETURN ONLY VALID JSON WITH THIS SHAPE:
{{
  "match_score": 0,
  "should_apply": "yes",
  "relocation_required": false,
  "visa_sponsorship_evidence": "yes",
  "fit_reasons": ["..."],
  "gaps": ["..."],
  "resume_keywords": ["..."],
  "cover_letter_angle": "...",
  "cover_letter": "..."
}}
""".strip()


def match_job(job, cfg):
    min_score = cfg.get("agent", {}).get("min_match_score", 65)

    prompt = build_prompt(job, cfg, min_score)
    result = call_llm_json(prompt)

    try:
        score = int(result.get("match_score", 0))
    except Exception:
        score = 0

    score = max(0, min(100, score))
    result["match_score"] = score

    relocation = result.get("relocation_required", False)
    if isinstance(relocation, str):
        relocation = relocation.strip().lower() in {"true", "yes", "1"}
    result["relocation_required"] = bool(relocation)

    visa = str(result.get("visa_sponsorship_evidence", "unclear")).strip().lower()
    if visa not in {"yes", "no", "unclear"}:
        visa = "unclear"
    result["visa_sponsorship_evidence"] = visa

    if (
        cfg.get("preferences", {}).get("visa_sponsorship_required_for_relocation", True)
        and result.get("relocation_required")
        and result.get("visa_sponsorship_evidence") != "yes"
    ):
        result["match_score"] = min(result["match_score"], 60)

    if result["match_score"] < min_score:
        result["cover_letter"] = ""

    return result


def main():
    print("Starting Gemini AI matching test...")

    cfg = load_config()

    good_job = {
        "id": "mock_good",
        "title": "Online Carnatic Vocal Instructor",
        "company": "Global Indian Music Academy",
        "location": "Remote",
        "remote": True,
        "url": "https://example.com/job1",
        "source": "mock",
        "description": (
            "We are looking for an experienced Carnatic vocal teacher to teach online classes "
            "to diaspora students. Must know varnams, kritis, ragam, niraval and swaram. "
            "Experience with curriculum design, online teaching, and producing backing tracks "
            "is a plus."
        ),
    }

    bad_job = {
        "id": "mock_bad",
        "title": "Pop Music Producer and Beatmaker",
        "company": "LA Studios",
        "location": "Los Angeles, CA",
        "remote": False,
        "url": "https://example.com/job2",
        "source": "mock",
        "description": (
            "Looking for a beat maker and pop music producer. Must know Ableton, synths, "
            "and modern pop production. Local candidates only."
        ),
    }

    tricky_job = {
        "id": "mock_tricky",
        "title": "Music Teacher - Indian Classical",
        "company": "London Academy of Arts",
        "location": "London, UK",
        "remote": False,
        "url": "https://example.com/job3",
        "source": "mock",
        "description": (
            "Seeking a music educator for our Indian classical department. Must have a Master's "
            "degree and teaching experience. Must already have the right to work in the UK. "
            "We do not offer visa sponsorship."
        ),
    }

    jobs = [
        ("GOOD JOB - Remote Carnatic teaching", good_job),
        ("BAD JOB - Pop producer, irrelevant", bad_job),
        ("TRICKY JOB - UK music teacher but no visa sponsorship", tricky_job),
    ]

    for label, job in jobs:
        print("\n" + "=" * 80)
        print(f"Testing: {label}")
        print("=" * 80)

        try:
            result = match_job(job, cfg)

            print(f"Job Title: {job['title']}")
            print(f"Location: {job['location']}")
            print(f"Match Score: {result.get('match_score')}")
            print(f"Should Apply: {result.get('should_apply')}")
            print(f"Relocation Required: {result.get('relocation_required')}")
            print(f"Visa Evidence: {result.get('visa_sponsorship_evidence')}")

            print("\nFit Reasons:")
            for reason in result.get("fit_reasons", []):
                print(f"- {reason}")

            print("\nGaps:")
            for gap in result.get("gaps", []):
                print(f"- {gap}")

            cover_letter = result.get("cover_letter", "")
            if cover_letter:
                print("\nCover Letter Preview:")
                print(cover_letter[:500])
            else:
                print("\nCover Letter: Not generated because score is below threshold.")

        except Exception as e:
            print(f"Error while testing job: {e}")

    print("\nGemini Day 1 test completed.")


if __name__ == "__main__":
    main()
