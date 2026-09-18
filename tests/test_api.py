from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline import ESGPipeline
from app.store import Store

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "documents" in data


def test_documents_and_corpus_stats():
    res1 = client.get("/api/documents")
    assert res1.status_code == 200
    assert isinstance(res1.json(), list)

    res2 = client.get("/api/corpus/stats")
    assert res2.status_code == 200
    assert "chunks" in res2.json()


def test_search_endpoint():
    response = client.post("/api/search", json={"query": "emissions", "top_k": 3})
    assert response.status_code == 200
    citations = response.json()
    assert isinstance(citations, list)


def test_analyze_qa_mode():
    payload = {
        "question": "What were Scope 1 and Scope 2 emissions?",
        "top_k": 5,
        "mode": "qa",
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "qa"
    assert "answer" in data
    assert "disclosure_coverage" in data
    assert "screening_signals" in data
    assert "pillars" in data
    assert isinstance(data["citations"], list)


def test_analyze_audit_mode():
    payload = {
        "question": "Perform full ESG audit",
        "top_k": 6,
        "mode": "audit",
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "audit"
    assert "pillars" in data
    assert len(data["pillars"]) == 3


def test_analyze_validation_errors():
    # Câu hỏi quá ngắn.
    response = client.post("/api/analyze", json={"question": "hi"})
    assert response.status_code == 422

    # top_k vượt giới hạn.
    response2 = client.post("/api/analyze", json={"question": "Valid question text", "top_k": 100})
    assert response2.status_code == 422


def test_analysis_response_exposes_evidence_not_orchestration_state():
    response = client.post("/api/analyze", json={"question": "What were Scope 1 emissions?"})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["citations"], list)
    assert "agent_route" not in data
    assert "agent_mode" not in data
    assert "plan" not in data
    assert "claims" not in data
    assert "criterion_bundles" not in data
    assert "trace" not in data


def test_analysis_has_page_citations(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "Example.pdf",
        [
            (
                7,
                "Scope 1 emissions fell 12% in 2024. Board audit and worker safety training covered 500 employees.",
            )
        ],
    )
    result = ESGPipeline(store).run(
        "Assess climate emissions safety employee governance audit", 5, mode="audit"
    )
    assert result.citations[0].page == 7
    assert result.citations[0].validated is True
    assert {p.pillar for p in result.pillars} == {"E", "S", "G"}
    assert result.disclosure_coverage >= 0.0
    assert all(0.0 <= p.disclosure_coverage <= 100.0 for p in result.pillars)
    assert all(0.0 <= p.evidence_quality <= 100.0 for p in result.pillars)
    assert result.limitations


def test_document_filter(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("a", "A.pdf", [(1, "carbon emissions were reduced")])
    store.add_document("b", "B.pdf", [(2, "carbon emissions increased")])
    result = ESGPipeline(store).run("carbon emissions", 5, ["b"], mode="qa")
    assert result.citations and all(c.document_id == "b" for c in result.citations)


def test_disclosure_target_without_baseline(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1", "Claims.pdf", [(3, "We aspire to achieve net-zero emissions by 2030.")]
    )
    result = ESGPipeline(store).run(
        "Review climate target and disclosure evidence", 5, mode="audit"
    )
    assert any("năm cơ sở" in signal for signal in result.screening_signals)
