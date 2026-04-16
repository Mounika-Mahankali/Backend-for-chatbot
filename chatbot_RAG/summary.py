from multimodal import get_response


def summarize_chat(messages):

    try:

        text = ""

        for m in messages:
            text += f"User: {m.message}\n"
            text += f"Bot: {m.response}\n"

        summary = get_response(
            f"Summarize this conversation:\n{text}"
        )

        return summary

    except Exception as e:
        return str(e)