from multimodal import get_response

conversation_history = []
conversation_summary = ""


def save_to_memory(user_input, response):

    global conversation_history

    conversation_history.append(
        f"User: {user_input}\nAssistant: {response}"
    )


def summarize_memory():

    global conversation_history
    global conversation_summary

    if not conversation_history:
        return conversation_summary

    prompt = f"""
    Summarize the following conversation briefly:

    {conversation_summary}

    {' '.join(conversation_history)}
    """

    summary = get_response(prompt)

    conversation_summary = summary
    conversation_history = []

    return conversation_summary


def get_memory():

    return conversation_summary