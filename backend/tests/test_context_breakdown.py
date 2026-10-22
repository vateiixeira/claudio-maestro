from claudio_maestro.contextusage import context_breakdown

FULL_USAGE = {
    "model": "claude-opus-5-5",
    "totalTokens": 84800,
    "rawMaxTokens": 400000,
    "maxTokens": 367000,
    "categories": [
        {"name": "Free space", "tokens": 281900, "kind": "free", "color": "x"},
        {"name": "System tools", "tokens": 15900, "kind": "used"},
        {"name": "Messages", "tokens": 35800, "kind": "used"},
        {"name": "Autocompact buffer", "tokens": 33000, "kind": "buffer"},
        {"name": "MCP tools", "tokens": 11600, "kind": "used"},
        {"name": "Skills", "tokens": 10000, "kind": "used"},
        {"name": "System prompt", "tokens": 7700, "kind": "used"},
        {"name": "System tools (deferred)", "tokens": 23800, "kind": "deferred"},
        {"name": "Memory files", "tokens": 2100, "kind": "used"},
        {"name": "Custom agents", "tokens": 1300, "kind": "used"},
        {"name": "MCP tools (deferred)", "tokens": 80300, "kind": "deferred"},
        {"name": "MCP server instructions", "tokens": 787, "kind": "used"},
        {"name": "Empty thing", "tokens": 0, "kind": "used"},
    ],
    "mcpTools": [
        {"name": "small", "serverName": "a", "tokens": 100, "isLoaded": True},
        {"name": "not_loaded", "serverName": "a", "tokens": 500, "isLoaded": False},
        {"name": "sem_flag", "serverName": "b", "tokens": 1900},
        {"name": "big", "serverName": "b", "tokens": 3000, "isLoaded": True},
    ],
    "memoryFiles": [
        {"path": "/p/CLAUDE.md", "type": "Project", "tokens": 300},
        {"path": "/h/CLAUDE.md", "type": "User", "tokens": 900},
    ],
    "agents": [
        {"agentType": "reviewer", "source": "projectSettings", "tokens": 100},
        {"agentType": "implementer", "source": "projectSettings", "tokens": 200},
    ],
    "skills": {
        "skillFrontmatter": [
            {"name": "brainstorming", "source": "plugin", "tokens": 400},
            {"name": "commit", "source": "user", "tokens": 600},
        ]
    },
}

OLD_USAGE = {
    "totalTokens": 1000,
    "maxTokens": 10000,
    "categories": [
        {"name": "Messages", "tokens": 500},
        {"name": "Free space", "tokens": 9000},
        {"name": "Compact buffer", "tokens": 400},
        {"name": "MCP tools (deferred)", "tokens": 100},
        {"name": "Hidden tools", "tokens": 50, "isDeferred": True},
        {"name": "Odd", "tokens": 10, "kind": "weird"},
    ],
}


def test_breakdown_orders_categories_for_display():
    names = [c["name"] for c in context_breakdown(FULL_USAGE)["categories"]]
    assert names == [
        "Messages", "System tools", "MCP tools", "Skills", "System prompt",
        "Memory files", "Custom agents", "MCP server instructions",
        "Autocompact buffer", "Free space",
        "MCP tools (deferred)", "System tools (deferred)",
    ]


def test_breakdown_drops_zero_token_categories():
    names = [c["name"] for c in context_breakdown(FULL_USAGE)["categories"]]
    assert "Empty thing" not in names


def test_breakdown_category_shape_and_model():
    b = context_breakdown(FULL_USAGE)
    assert b["model"] == "claude-opus-5-5"
    assert b["categories"][0] == {"name": "Messages", "tokens": 35800, "kind": "used"}
    assert "color" not in b["categories"][9]


def test_breakdown_uses_raw_max_tokens_and_same_percent_base():
    b = context_breakdown(FULL_USAGE)
    assert (b["total_tokens"], b["max_tokens"], b["percent"]) == (84800, 400000, 21.2)


def test_breakdown_falls_back_to_max_tokens_and_null_model():
    b = context_breakdown(OLD_USAGE)
    assert (b["max_tokens"], b["percent"], b["model"]) == (10000, 10.0, None)


def test_breakdown_classifies_by_name_without_kind():
    kinds = {c["name"]: c["kind"] for c in context_breakdown(OLD_USAGE)["categories"]}
    assert kinds["Free space"] == "free" and kinds["Compact buffer"] == "buffer"
    assert kinds["MCP tools (deferred)"] == "deferred" and kinds["Hidden tools"] == "deferred"
    assert kinds["Messages"] == "used" and kinds["Odd"] == "used"


def test_breakdown_classifies_deferred_suffix_ignoring_case():
    usage = {**OLD_USAGE, "categories": [{"name": "X (Deferred)", "tokens": 5}]}
    assert context_breakdown(usage)["categories"][0]["kind"] == "deferred"


def test_breakdown_mcp_tools_loaded_flag_defaults_true_and_sorted():
    tools = context_breakdown(FULL_USAGE)["mcp_tools"]
    assert [t["tokens"] for t in tools] == sorted((t["tokens"] for t in tools), reverse=True)
    by_name = {t["name"]: t for t in tools}
    assert by_name["sem_flag"]["loaded"] is True
    assert by_name["not_loaded"]["loaded"] is False
    assert by_name["big"] == {"name": "big", "server": "b", "tokens": 3000, "loaded": True}


def test_breakdown_lists_memory_agents_and_skills():
    b = context_breakdown(FULL_USAGE)
    assert b["memory_files"] == [
        {"path": "/h/CLAUDE.md", "tokens": 900},
        {"path": "/p/CLAUDE.md", "tokens": 300},
    ]
    assert b["agents"] == [
        {"name": "implementer", "tokens": 200},
        {"name": "reviewer", "tokens": 100},
    ]
    assert b["skills"] == [
        {"name": "commit", "tokens": 600},
        {"name": "brainstorming", "tokens": 400},
    ]


def test_breakdown_over_limit_caps_percent_at_100():
    usage = {
        **FULL_USAGE,
        "totalTokens": 410000,
        "categories": [c for c in FULL_USAGE["categories"] if c["name"] != "Free space"],
    }
    b = context_breakdown(usage)
    assert b["percent"] == 100.0
    assert b["total_tokens"] == 410000
    assert all(c["tokens"] > 0 for c in b["categories"])


def test_breakdown_rejects_unusable_response():
    assert context_breakdown(None) is None
    assert context_breakdown("x") is None
    assert context_breakdown({"totalTokens": 10}) is None
    assert context_breakdown({"totalTokens": True, "rawMaxTokens": 100}) is None
    assert context_breakdown({"totalTokens": -1, "rawMaxTokens": 100}) is None
    assert context_breakdown({"totalTokens": 1, "rawMaxTokens": 0, "maxTokens": 0}) is None


def test_breakdown_ignores_malformed_lists():
    b = context_breakdown(
        {
            **FULL_USAGE,
            "categories": "x",
            "mcpTools": "x",
            "memoryFiles": [None, {"path": 3, "tokens": 1}],
            "agents": {"a": 1},
            "skills": {"skillFrontmatter": [None, {"name": 3}]},
        }
    )
    assert b["categories"] == [] and b["mcp_tools"] == [] and b["memory_files"] == []
    assert b["agents"] == [] and b["skills"] == []
    assert context_breakdown({**FULL_USAGE, "skills": "x"})["skills"] == []


def test_breakdown_skips_entries_with_invalid_tokens():
    usage = {
        **FULL_USAGE,
        "categories": [
            {"name": "Messages", "tokens": "5"},
            {"name": "Bool", "tokens": True},
            {"name": "Neg", "tokens": -3},
            {"name": "Ok", "tokens": 7},
            {"tokens": 9},
        ],
    }
    assert [c["name"] for c in context_breakdown(usage)["categories"]] == ["Ok"]


def test_breakdown_unhashable_kind_falls_back_to_name():
    usage = {
        **OLD_USAGE,
        "categories": [
            {"name": "Free space", "tokens": 9, "kind": ["free"]},
            {"name": "Messages", "tokens": 5, "kind": {"a": 1}},
            {"name": "Compact buffer", "tokens": 3, "kind": 7},
        ],
    }
    kinds = {c["name"]: c["kind"] for c in context_breakdown(usage)["categories"]}
    assert kinds == {"Free space": "free", "Messages": "used", "Compact buffer": "buffer"}
