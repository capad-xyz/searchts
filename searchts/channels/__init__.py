# -*- coding: utf-8 -*-
"""
Channel registry — lists all supported platforms for doctor checks.
"""

from typing import List, Optional
from .base import Channel

# Import all channels
from .web import WebChannel
from .github import GitHubChannel
from .twitter import TwitterChannel
from .youtube import YouTubeChannel
from .tiktok import TikTokChannel
from .instagram import InstagramChannel
from .redditvideo import RedditVideoChannel
from .reddit import RedditChannel
from .rss import RSSChannel
from .exa_search import ExaSearchChannel
from .linkedin import LinkedInChannel


ALL_CHANNELS: List[Channel] = [
    GitHubChannel(),
    TwitterChannel(),
    YouTubeChannel(),
    TikTokChannel(),
    InstagramChannel(),
    # RedditVideoChannel is listed before RedditChannel so v.redd.it / video post
    # permalinks route to the no-login transcription path first.
    RedditVideoChannel(),
    RedditChannel(),
    LinkedInChannel(),
    RSSChannel(),
    ExaSearchChannel(),
    WebChannel(),
]


def get_channel(name: str) -> Optional[Channel]:
    """Get a channel by name."""
    for ch in ALL_CHANNELS:
        if ch.name == name:
            return ch
    return None


def get_all_channels() -> List[Channel]:
    """Get all registered channels."""
    return ALL_CHANNELS


__all__ = [
    "Channel",
    "ALL_CHANNELS",
    "get_channel", "get_all_channels",
]
