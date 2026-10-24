"""The Groq models Glance uses. This is the one place to change them."""

# Explaining text: a small model is enough, and answers quickly.
TEXT = "openai/gpt-oss-20b"
# Explaining an image: Groq's preview model that reads images, which the text model
# cannot. It may change or disappear.
VISION = "qwen/qwen3.8-27b"
# Translation quality, especially for less common languages, depends on size far more
# than an explanation does.
TRANSLATE = "openai/gpt-oss-120b"
# A reasoning model thinks before it answers; a low effort keeps that short.
REASONING_EFFORT = "low"
