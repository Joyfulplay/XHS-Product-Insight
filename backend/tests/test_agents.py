from app.agents.product_insight_agent import ProductInsightAgent


def test_agent_analyze_returns_result():
    agent = ProductInsightAgent()
    result = agent.analyze("sample product review text", [])
    assert "summary" in result
    assert "insights" in result
