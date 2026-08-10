import os

FILES = {
    ".github/workflows/music-agent.yml": """name: Music Job Agent Gemini

on:
  workflow_dispatch:
  schedule:
    - cron: "30 1 */3 * *"

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run Gemini test
        if: github.event_name == 'workflow_dispatch'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL }}
          OPENAI_MODEL: ${{ secrets.OPENAI_MODEL }}
        run: python test_brain.py
      - name: Run live agent
        if: github.event_name == 'schedule'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL }}
          OPENAI_MODEL: ${{ secrets.OPENAI_MODEL }}
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_PORT: ${{ secrets.SMTP_PORT }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASS: ${{ secrets.SMTP_PASS }}
          EMAIL_TO: ${{ secrets.EMAIL_TO }}
          EMAIL_FROM: ${{ secrets.EMAIL_FROM }}
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          JOUBLE_API_KEY: ${{ secrets.JOUBLE_API_KEY }}
        run: |
          if [ -f job_agent.py ]; then python job_agent.py; else echo "job_agent.py not added yet"; fi
""",

    "requirements.txt": """openai>=1.40.0
PyYAML>=6.0.1
requests>=2.31.0
feedparser>=6.0.11
""",

    "config.yaml": """agent:
  min_match_score: 65
  max_jobs_to_fetch_per_source: 25
  max_jobs_to_match: 50
  max_description_chars: 6000
  max_days_old: 4
  send_empty_digest: false

candidate:
  name: "Ezhilarasi Murugesan"
  headline: "Carnatic Music Educator · Performing Vocalist & Composer · Doctoral Research Scholar"
  location: "Chennai, Tamil Nadu, India"
  email: "isaiezhil22@gmail.com"
  languages: [Tamil, English, Hindi]
  target_roles:
    - Carnatic music teacher
    - Indian classical music teacher
    - Vocal instructor
    - Online music teacher
    - Music educator
    - Music curriculum designer
    - Teaching artist
    - Music lecturer
    - Assistant professor of music
    - Ethnomusicology faculty
    - Music education researcher
    - Composer
    - Performing vocalist
    - Music programme coordinator
    - Arts education specialist
  core_skills:
    - Carnatic vocal pedagogy
    - Varnam, kriti, ragam, niraval and swaram training
    - Bhajans and devotional repertoire
    - Curriculum and syllabus design
    - Performance preparation and stagecraft
    - Music theory and notating songs
    - Composition and songwriting for Tamil light music
    - Online and remote music instruction
    - Karaoke and backing-track production
    - Music education for autistic children
    - Inclusive music education
    - Vocal, violin and guitar instruction
  education:
    - "PhD in Music, in progress, VISTAS, 2024–2028"
    - "M.A. in Indian Music, University of Madras, 2018"
    - "Diploma in Carnatic Music Vocal, Kalakshetra Foundation, 2014"
    - "Bachelor of Music, University of Madras, 2013"
  experience_highlights:
    - "Over 10 years of music teaching experience"
    - "Music Teacher at Vanshi Manthan Vidyashram, Edexcel–Pearson affiliated"
    - "Senior Music Teacher at Sangeetha Kalalayaa – The School of Fine Arts"
    - "Music Teacher at Niharika Multi-Activity Centre"
    - "Independent online and home-based Carnatic and light music educator"
    - "Trained students for competitions, grade exams and performances"
    - "Experience teaching children, all age groups, and inclusive learning settings"
  performance_profile:
    - "Active Carnatic vocal performer"
    - "Founder-performer of the band On the Streets of Chennai"
    - "Original Tamil light music composer"
    - "Vocalist, violinist and guitarist"
    - "Collaborations with sabhas, Bharatanatyam academies and cultural festivals"
    - "Contributor to Aanmajothi – Music to Schools initiative"
  research_profile:
    - "Doctoral research in Indian Music, Nagarathar Music Traditions"
    - "Presented paper at 9th Annual World Music Conference 2025"
    - "Member of European Society for the Cognitive Sciences of Music"
  work_authorisation:
    nationality: "Indian"
    open_to_remote: true
    open_to_india: true
    open_to_relocation: true
    needs_visa_sponsorship_for_relocation: true

preferences:
  job_types: [full-time, part-time, contract, freelance, remote, online, academic, performance]
  open_to_remote: true
  open_to_india: true
  open_to_relocation: true
  visa_sponsorship_required_for_relocation: true
  target_regions:
    - India
    - Remote
    - Singapore
    - Malaysia
    - UAE
    - Qatar
    - Oman
    - UK
    - USA
    - Canada
    - Australia
    - New Zealand
    - Germany
    - France
    - Netherlands

search_queries:
  - "Carnatic music teacher"
  - "Indian classical music teacher"
  - "Carnatic vocal instructor"
  - "Indian music teacher"
  - "online music teacher"
  - "remote music teacher"
  - "vocal instructor"
  - "music educator"
  - "music curriculum designer"
  - "teaching artist music"
  - "ethnomusicology lecturer"
  - "music lecturer"
  - "assistant professor music"
  - "Tamil light music composer"
  - "music teacher special needs"
  - "music education autism"

sources:
  adzuna:
    enabled: false
    countries: [in, gb, us, ca, au, sg, nz]
  jooble:
    enabled: false
  rss:
    enabled: false
    feeds: []
""",

    "test_brain.py": """import json, os, re, yaml
from openai import OpenAI

def load_config():
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)

def parse_json_loose(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]
    return json.loads(text)

def call_llm_json(prompt):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing. Add Gemini key as OPENAI_API_KEY in GitHub Secrets.")
    client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    model = os.getenv("OPENAI_MODEL", "gemini-2.0-flash")
    messages = [{"role": "system", "content": "You are a precise job-matching engine. Return only valid JSON."},
                {"role": "user", "content": prompt}]
    try:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1, response_format={"type":"json_object"})
    except Exception:
        resp = client.chat.completions.create(model=model, messages=messages, temperature=0.1)
    return parse_json_loose(resp.choices[0].message.content)

def build_prompt(job, cfg, min_score):
    candidate = cfg.get("candidate", {})
    preferences = cfg.get("preferences", {})
    job_copy = dict(job)
    max_chars = cfg.get("agent", {}).get("max_description_chars", 6000)
    job_copy["description"] = (job_copy.get("description") or "")[:max_chars]
    return f\"\"\"
You are a global job-search agent for Ezhilarasi Murugesan.
CANDIDATE PROFILE:
{json.dumps(candidate, indent=2, ensure_ascii=False)}
SEARCH PREFERENCES:
{json.dumps(preferences, indent=2, ensure_ascii=False)}
JOB:
{json.dumps(job_copy, indent=2, ensure_ascii=False)}
TASK: Evaluate how well this job matches the candidate.
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
\"\"\".strip()

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
    if (cfg.get("preferences", {}).get("visa_sponsorship_required_for_relocation", True)
        and result.get("relocation_required")
        and result.get("visa_sponsorship_evidence") != "yes"):
        result["match_score"] = min(result["match_score"], 60)
    if result["match_score"] < min_score:
        result["cover_letter"] = ""
    return result

def main():
    print("Starting Gemini AI matching test...")
    cfg = load_config()
    jobs = [
        ("GOOD JOB - Remote Carnatic teaching", {
            "id": "mock_good", "title": "Online Carnatic Vocal Instructor",
            "company": "Global Indian Music Academy", "location": "Remote",
            "remote": True, "url": "https://example.com/job1", "source": "mock",
            "description": "We are looking for an experienced Carnatic vocal teacher to teach online classes to diaspora students. Must know varnams, kritis, ragam, niraval and swaram. Experience with curriculum design, online teaching, and producing backing tracks is a plus."
        }),
        ("BAD JOB - Pop producer, irrelevant", {
            "id": "mock_bad", "title": "Pop Music Producer and Beatmaker",
            "company": "LA Studios", "location": "Los Angeles, CA",
            "remote": False, "url": "https://example.com/job2", "source": "mock",
            "description": "Looking for a beat maker and pop music producer. Must know Ableton, synths, and modern pop production. Local candidates only."
        }),
        ("TRICKY JOB - UK music teacher but no visa sponsorship", {
            "id": "mock_tricky", "title": "Music Teacher - Indian Classical",
            "company": "London Academy of Arts", "location": "London, UK",
            "remote": False, "url": "https://example.com/job3", "source": "mock",
            "description": "Seeking a music educator for our Indian classical department. Must have a Master's degree and teaching experience. Must already have the right to work in the UK. We do not offer visa sponsorship."
        })
    ]
    for label, job in jobs:
        print("\\n" + "=" * 80)
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
            print("\\nFit Reasons:")
            for reason in result.get("fit_reasons", []):
                print(f"- {reason}")
            print("\\nGaps:")
            for gap in result.get("gaps", []):
                print(f"- {gap}")
            cover_letter = result.get("cover_letter", "")
            if cover_letter:
                print("\\nCover Letter Preview:")
                print(cover_letter[:500])
            else:
                print("\\nCover Letter: Not generated because score is below threshold.")
        except Exception as e:
            print(f"Error while testing job: {e}")
    print("\\nGemini Day 1 test completed.")

if __name__ == "__main__":
    main()
"""
}

for path, content in FILES.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Created: {path}")

print("\nAll files created successfully!")
print("Next step: Go to Actions tab and run 'Music Job Agent Gemini' workflow.")