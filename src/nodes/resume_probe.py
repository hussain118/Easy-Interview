from src.nodes._topic_node import make_prepare_node, make_wait_node

resume_probe = make_prepare_node("resume_probe")
resume_probe_wait = make_wait_node("resume_probe")
