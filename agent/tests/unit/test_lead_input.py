"""Вход лида: пользовательская задача Рана vs дефолтная формулировка."""

from core.lead.graph import _LEAD_TASK, _lead_input


def test_default_task_formats_repo_url():
    msg = _lead_input("https://github.com/o/r")["messages"][0]
    assert "https://github.com/o/r" in msg.content
    assert msg.content == _LEAD_TASK.format(repo_url="https://github.com/o/r")


def test_custom_instructions_replace_default():
    msg = _lead_input("u", instructions="опиши каждую функцию в {repo_url}")["messages"][0]
    assert msg.content == "опиши каждую функцию в u"


def test_braces_in_instructions_do_not_crash():
    msg = _lead_input("u", instructions="выведи {'a': 1} и {unknown}")["messages"][0]
    assert msg.content == "выведи {'a': 1} и {unknown}"


def test_blank_instructions_fall_back_to_default():
    msg = _lead_input("u", instructions="   ")["messages"][0]
    assert msg.content == _LEAD_TASK.format(repo_url="u")
