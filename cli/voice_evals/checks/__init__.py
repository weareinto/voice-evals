"""Built-in checks.

session_metrics and scoring_checks are uploaded as-is to LangSmith as online code
evaluators (entry point: perform_eval(run)). reply_checks scores single replies in the
release gate. Set EVIDENCE = [] on a module to collect example lines (used by triage).
"""
