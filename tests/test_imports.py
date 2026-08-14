"""All Phase 1 modules must import cleanly (no syntax errors, no missing
deps, no import-time side effects that require live network access)."""


def test_config_imports():
    import src.config  # noqa: F401


def test_provider_imports():
    import src.providers.openai_client  # noqa: F401


def test_agent_imports():
    import src.agents.jd_parser  # noqa: F401
    import src.agents.resume_parser  # noqa: F401
    import src.agents.github_agent  # noqa: F401
    import src.agents.gap_analysis  # noqa: F401
    import src.agents.question_planner  # noqa: F401


def test_run_prep_module_imports():
    import importlib

    spec = importlib.util.spec_from_file_location("run_prep", "run_prep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
