"""Shared fixtures for jobsearch-mcp tests."""

import pytest
import respx


@pytest.fixture
def mock_httpx():
    """Context manager that mocks all outbound httpx calls."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def sample_job_html():
    return "<html><body><h1>Software Engineer</h1><p>Apply now for this great role.</p></body></html>"


@pytest.fixture
def sample_jd():
    return (
        "We are looking for a Senior Python Developer with 5+ years experience. "
        "Must have: FastAPI, PostgreSQL, Docker, Kubernetes. "
        "Nice to have: Redis, Qdrant, TypeScript. "
        "Remote OK. Salary: $120,000 - $160,000."
    )


@pytest.fixture
def sample_resume():
    return (
        "Software engineer with 7 years experience. "
        "Expert in Python, FastAPI, PostgreSQL, Docker. "
        "Experience with Redis and vector databases. "
        "Open to remote positions."
    )


@pytest.fixture
def sample_profile():
    return {
        "name": "John Doe",
        "email": "john@example.com",
        "location": "Remote",
        "target_roles": ["Software Engineer", "Python Developer"],
        "remote_preference": "remote_only",
        "experience": [
            {
                "title": "Senior Software Engineer",
                "company": "Acme Corp",
                "duration": "Jan 2020 - Present",
                "highlights": [
                    "Built FastAPI microservices",
                    "Led team of 5 engineers",
                ],
            }
        ],
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        "education": [
            {
                "degree": "BS Computer Science",
                "institution": "State University",
                "year": "2017",
            }
        ],
        "certifications": [],
        "summary": "Senior Python developer with 7 years experience building scalable APIs.",
        "work_authorization": "US Citizen",
        "salary_min": 120000,
        "salary_max": 160000,
        "notification_email": "john@example.com",
    }
