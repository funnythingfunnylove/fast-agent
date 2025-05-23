"""
Tests for the Prompt class.
"""

import base64
import os
import tempfile
from pathlib import Path

from mcp.types import EmbeddedResource, ImageContent, PromptMessage, TextContent

from mcp_agent.core.prompt import Prompt
from mcp_agent.mcp.prompt_message_multipart import PromptMessageMultipart


def test_user_method():
    """Test the Prompt.user method."""
    # Test with simple text
    message = Prompt.user("Hello, world!")

    assert isinstance(message, PromptMessageMultipart)
    assert message.role == "user"
    assert len(message.content) == 1
    assert isinstance(message.content[0], TextContent)
    assert message.content[0].text == "Hello, world!"

    # Test with multiple items
    message = Prompt.user("Hello,", "How are you?")

    assert isinstance(message, PromptMessageMultipart)
    assert message.role == "user"
    assert len(message.content) == 2
    assert message.content[0].text == "Hello,"
    assert message.content[1].text == "How are you?"


def test_assistant_method():
    """Test the Prompt.assistant method."""
    # Test with simple text
    message = Prompt.assistant("I'm doing well, thanks!")

    assert isinstance(message, PromptMessageMultipart)
    assert message.role == "assistant"
    assert len(message.content) == 1
    assert isinstance(message.content[0], TextContent)
    assert message.content[0].text == "I'm doing well, thanks!"


def test_message_method():
    """Test the Prompt.message method."""
    # Test with user role (default)
    message = Prompt.message("Hello")

    assert isinstance(message, PromptMessageMultipart)
    assert message.role == "user"

    # Test with assistant role
    message = Prompt.message("Hello", role="assistant")

    assert isinstance(message, PromptMessageMultipart)
    assert message.role == "assistant"


def test_with_file_paths():
    """Test the Prompt class with file paths."""
    # Create temporary files
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as text_file:
        text_file.write(b"Hello, world!")
        text_path = text_file.name

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
        image_file.write(b"fake image data")
        image_path = image_file.name

    try:
        # Test with text file
        message = Prompt.user("Check this file:", Path(text_path))

        assert message.role == "user"
        assert len(message.content) == 2
        assert message.content[0].text == "Check this file:"
        assert isinstance(message.content[1], EmbeddedResource)
        assert message.content[1].resource.text == "Hello, world!"

        # Test with image file
        message = Prompt.assistant("Here's the image:", Path(image_path))

        assert message.role == "assistant"
        assert len(message.content) == 2
        assert message.content[0].text == "Here's the image:"
        assert isinstance(message.content[1], ImageContent)

        # Decode the base64 data
        decoded = base64.b64decode(message.content[1].data)
        assert decoded == b"fake image data"

    finally:
        # Clean up
        os.unlink(text_path)
        os.unlink(image_path)


def test_conversation_method():
    """Test the Prompt.conversation method."""
    # Create conversation from PromptMessageMultipart objects
    user_msg = Prompt.user("Hello")
    assistant_msg = Prompt.assistant("Hi there!")

    conversation = Prompt.conversation(user_msg, assistant_msg)

    assert len(conversation) == 2
    assert all(isinstance(msg, PromptMessage) for msg in conversation)
    assert conversation[0].role == "user"
    assert conversation[1].role == "assistant"

    # Test with mixed inputs
    mixed_conversation = Prompt.conversation(
        user_msg,
        {"role": "assistant", "content": TextContent(type="text", text="Direct dict!")},
        Prompt.user("Another message"),
    )

    assert len(mixed_conversation) == 3
    assert mixed_conversation[0].role == "user"
    assert mixed_conversation[1].role == "assistant"
    assert mixed_conversation[1].content.text == "Direct dict!"
    assert mixed_conversation[2].role == "user"


def test_from_multipart_method():
    """Test the Prompt.from_multipart method."""
    # Create a list of multipart messages
    multipart_msgs = [
        Prompt.user("Hello"),
        Prompt.assistant("Hi there!"),
        Prompt.user("How are you?"),
    ]

    # Convert to PromptMessages
    messages = Prompt.from_multipart(multipart_msgs)

    assert len(messages) == 3
    assert all(isinstance(msg, PromptMessage) for msg in messages)
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[2].role == "user"

    # Test with PromptMessageMultipart instances containing multiple content items
    complex_multipart = [
        Prompt.user("Hello,", "How are you?"),
        Prompt.assistant("I'm fine,", "Thanks for asking!"),
    ]

    messages = Prompt.from_multipart(complex_multipart)

    assert len(messages) == 4  # 2 content items in each multipart = 4 total messages
    assert messages[0].role == "user"
    assert messages[1].role == "user"
    assert messages[2].role == "assistant"
    assert messages[3].role == "assistant"
