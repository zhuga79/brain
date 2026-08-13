"""Mock-based unit tests for brain-vector.

Mocks chromadb and sentence-transformers to test CLI logic without heavy deps.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add runtime/bin to sys.path so we can import brain-vector as a module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "runtime" / "bin"))

# Mock dependencies before importing.
#
# The mocks must stay in sys.modules for the whole session, not just for the
# import: brain-vector imports chromadb and sentence_transformers lazily inside
# _check_deps(), which runs when a command is invoked — long after this block
# exits. Scoping the patch to the import only made these tests pass wherever the
# real packages happened to be installed and fail everywhere else.
mock_chroma = MagicMock()
mock_st = MagicMock()
sys.modules["chromadb"] = mock_chroma
sys.modules["sentence_transformers"] = mock_st

with patch.dict(sys.modules, {"chromadb": mock_chroma, "sentence_transformers": mock_st}):
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("brain_vector", str(Path(__file__).resolve().parent.parent.parent / "runtime" / "bin" / "brain-vector"))
    bv = loader.load_module()
    sys.modules["brain_vector"] = bv


@pytest.fixture
def mock_brain(tmp_path):
    brain = tmp_path / "brain"
    brain.mkdir()
    (brain / ".brain" / "index").mkdir(parents=True)
    search_jsonl = brain / ".brain" / "index" / "search.jsonl"
    search_jsonl.write_text(
        json.dumps({"id": "page1", "text": "hello world", "title": "Page 1", "path": "page1.md"}) + "\n" +
        json.dumps({"id": "page2", "text": "foo bar", "title": "Page 2", "path": "page2.md"}) + "\n",
        encoding="utf-8"
    )
    return brain


class TestBrainVectorLogic:
    def test_score_from_distance(self):
        assert bv._score_from_distance(0.1) == 0.9
        assert bv._score_from_distance(1.0) == 0.0
        assert bv._score_from_distance(0.0) == 1.0
        assert bv._score_from_distance(None) is None
        assert bv._score_from_distance("invalid") is None

    def test_support_matrix_json(self, capsys):
        bv.cmd_support(json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "primary" in data
        assert "fallback" in data

    def test_support_matrix_text(self, capsys):
        bv.cmd_support(json_mode=False)
        out = capsys.readouterr().out
        assert "brain-vector support matrix" in out
        assert "BM25" in out

    @patch.object(bv, "_get_client")
    def test_status_missing_dir(self, mock_get_client, mock_brain, capsys):
        bv.cmd_status(mock_brain / "nonexistent")
        out = capsys.readouterr().out
        assert "vector index: not built" in out

    @patch.object(bv, "_get_client")
    def test_status_present(self, mock_get_client, mock_brain, capsys):
        vec_dir = mock_brain / ".brain" / "vector"
        vec_dir.mkdir(parents=True)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_col = MagicMock()
        mock_col.count.return_value = 10
        mock_client.get_collection.return_value = mock_col
        bv.cmd_status(mock_brain)
        out = capsys.readouterr().out
        assert "vector index: present" in out
        assert "documents : 10" in out

    @patch.object(bv, "_load_search_docs")
    @patch.object(bv, "_get_client")
    @patch("sentence_transformers.SentenceTransformer")
    def test_index_rebuild(self, mock_st_class, mock_get_client, mock_load_docs, mock_brain, capsys):
        mock_load_docs.return_value = [
            {"id": "doc1", "text": "content1", "title": "Title 1"},
            {"id": "doc2", "text": "content2", "title": "Title 2"},
        ]
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_col = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_col
        mock_model = MagicMock()
        mock_st_class.return_value = mock_model
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[0.1]*384, [0.2]*384])
        bv.cmd_index_rebuild(mock_brain)
        out = capsys.readouterr().out
        assert "OK: vector index built" in out
        assert "2 documents" in out
        mock_col.add.assert_called_once()

    @patch.object(bv, "_get_client")
    @patch.object(bv, "_get_collection")
    @patch.object(bv, "_load_model")
    def test_search_json(self, mock_load_model, mock_get_col, mock_get_client, mock_brain, capsys):
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[0.1]*384])
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        mock_col.count.return_value = 5
        mock_col.query.return_value = {
            "ids": [["doc1"]],
            "documents": [["content1"]],
            "metadatas": [[{"title": "Title 1", "path": "p1.md"}]],
            "distances": [[0.1]]
        }
        bv.cmd_search(mock_brain, "test query", top_k=5, json_mode=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["ok"] is True
        assert len(data["results"]) == 1
        assert data["results"][0]["score"] == 0.9

    @patch.object(bv, "_get_client")
    @patch.object(bv, "_get_collection")
    @patch.object(bv, "_load_model")
    def test_search_text(self, mock_load_model, mock_get_col, mock_get_client, mock_brain, capsys):
        mock_model = MagicMock()
        mock_load_model.return_value = mock_model
        mock_model.encode.return_value = MagicMock(tolist=lambda: [[0.1]*384])
        mock_col = MagicMock()
        mock_get_col.return_value = mock_col
        mock_col.count.return_value = 5
        mock_col.query.return_value = {
            "ids": [["doc1"]],
            "documents": [["content1"]],
            "metadatas": [[{"title": "Title 1", "path": "p1.md"}]],
            "distances": [[0.1]]
        }
        bv.cmd_search(mock_brain, "test query", top_k=5, json_mode=False)
        out = capsys.readouterr().out
        assert "1. [0.9] Title 1" in out

    def test_load_search_docs_missing(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            bv._load_search_docs(tmp_path)
        out = capsys.readouterr().err
        assert "BM25 index not built" in out

    def test_load_search_docs_valid(self, mock_brain):
        docs = bv._load_search_docs(mock_brain)
        assert len(docs) == 2
        assert docs[0]["id"] == "page1"

    @patch("subprocess.run")
    def test_cmd_setup_no_yes(self, mock_run, mock_brain, capsys):
        bv.cmd_setup(mock_brain, yes=False)
        out = capsys.readouterr().out
        assert "did not install anything" in out
        mock_run.assert_not_called()

    @patch("subprocess.run")
    @patch.object(bv, "_deps_available")
    @patch.object(bv, "_get_client")
    @patch("sentence_transformers.SentenceTransformer")
    def test_cmd_setup_yes(self, mock_st, mock_client, mock_deps, mock_run, mock_brain, capsys):
        mock_run.return_value = MagicMock(returncode=0)
        mock_deps.return_value = True
        bv.cmd_setup(mock_brain, yes=True)
        out = capsys.readouterr().out
        assert "OK: vector dependencies installed" in out
        mock_run.assert_called_once()

    def test_vector_dir(self, tmp_path):
        brain = tmp_path / "brain"
        assert bv._vector_dir(brain) == brain / ".brain" / "vector"

    def test_vendor_dir(self, tmp_path):
        brain = tmp_path / "brain"
        assert bv._vendor_dir(brain) == brain / ".brain" / "vector" / "vendor"

    @patch("os.environ.get")
    def test_brain_path_env(self, mock_env, tmp_path):
        p = tmp_path / "mybrain"
        p.mkdir()
        mock_env.return_value = str(p)
        assert bv._brain_path() == p

    @patch.object(bv, "_check_deps")
    @patch("chromadb.PersistentClient")
    def test_get_client(self, mock_pc, mock_check, tmp_path):
        vec_dir = tmp_path / "vec"
        bv._get_client(vec_dir)
        assert vec_dir.exists()
        mock_pc.assert_called_once_with(path=str(vec_dir))

    def test_get_collection_success(self):
        client = MagicMock()
        mock_col = MagicMock()
        client.get_collection.return_value = mock_col
        assert bv._get_collection(client, create=False) == mock_col

    def test_get_collection_create(self):
        client = MagicMock()
        mock_col = MagicMock()
        client.get_or_create_collection.return_value = mock_col
        assert bv._get_collection(client, create=True) == mock_col

    def test_get_collection_fail(self, capsys):
        client = MagicMock()
        client.get_collection.side_effect = Exception("fail")
        with pytest.raises(SystemExit):
            bv._get_collection(client, create=False)
        out = capsys.readouterr().err
        assert "collection error" in out

    @patch.object(bv, "_add_vendor_to_syspath")
    def test_check_deps_success(self, mock_add):
        with patch.dict(sys.modules, {"chromadb": MagicMock(), "sentence_transformers": MagicMock()}):
            bv._check_deps()

    @patch.object(bv, "_add_vendor_to_syspath")
    def test_check_deps_fail(self, mock_add, capsys):
        with patch.dict(sys.modules, {"chromadb": None, "sentence_transformers": None}):
            with pytest.raises(SystemExit):
                bv._check_deps()
        out = capsys.readouterr().err
        assert "dependency missing" in out

    @patch("pathlib.Path.exists")
    def test_add_vendor_to_syspath(self, mock_exists):
        mock_exists.return_value = True
        with patch("os.environ.get") as mock_env:
            mock_env.return_value = "/tmp/brain"
            bv._add_vendor_to_syspath()
            assert "/tmp/brain/.brain/vector/vendor" in sys.path

    @patch.object(bv, "_check_deps")
    def test_search_no_results(self, mock_check, capsys):
        client = MagicMock()
        with patch.object(bv, "_get_client", return_value=client):
            with patch.object(bv, "_get_collection", return_value=MagicMock(count=lambda: 5, query=lambda **kwargs: {})):
                with patch.object(bv, "_load_model", return_value=MagicMock()):
                    bv.cmd_search(Path("/tmp"), "q", 5, json_mode=False)
                    assert "No results." in capsys.readouterr().out

    @patch.object(bv, "_check_deps")
    def test_search_no_results_json(self, mock_check, capsys):
        client = MagicMock()
        with patch.object(bv, "_get_client", return_value=client):
            with patch.object(bv, "_get_collection", return_value=MagicMock(count=lambda: 5, query=lambda **kwargs: {})):
                with patch.object(bv, "_load_model", return_value=MagicMock()):
                    bv.cmd_search(Path("/tmp"), "q", 5, json_mode=True)
                    data = json.loads(capsys.readouterr().out)
                    assert data["results"] == []

    @patch.object(bv, "_check_deps")
    def test_search_empty_index(self, mock_check, capsys):
        client = MagicMock()
        with patch.object(bv, "_get_client", return_value=client):
            with patch.object(bv, "_get_collection", return_value=MagicMock(count=lambda: 0)):
                with patch.object(bv, "_load_model", return_value=MagicMock()):
                    with pytest.raises(SystemExit):
                        bv.cmd_search(Path("/tmp"), "q", 5, json_mode=False)
                    assert "index is empty" in capsys.readouterr().err

    @patch.object(bv, "_add_vendor_to_syspath")
    def test_deps_available_true(self, mock_add):
        with patch.dict(sys.modules, {"chromadb": MagicMock(), "sentence_transformers": MagicMock()}):
            assert bv._deps_available() is True

    @patch.object(bv, "_load_search_docs")
    def test_index_rebuild_no_docs(self, mock_load, mock_brain, capsys):
        mock_load.return_value = []
        with pytest.raises(SystemExit):
            bv.cmd_index_rebuild(mock_brain)
        assert "no documents in BM25 index" in capsys.readouterr().out

    @patch.object(bv, "_load_search_docs")
    @patch.object(bv, "_get_client")
    @patch("sentence_transformers.SentenceTransformer")
    def test_index_rebuild_no_valid_docs(self, mock_st, mock_client, mock_load, mock_brain, capsys):
        mock_load.return_value = [{"something": "else"}]
        mock_client.return_value = MagicMock()
        with pytest.raises(SystemExit):
            bv.cmd_index_rebuild(mock_brain)
        assert "no indexable documents found" in capsys.readouterr().out

    def test_main_no_args(self, capsys):
        with patch("sys.argv", ["brain-vector"]):
            with pytest.raises(SystemExit) as e:
                bv.main()
            assert e.value.code == 0
            assert "usage:" in capsys.readouterr().out

    @patch.object(bv, "cmd_status")
    def test_main_status(self, mock_status):
        with patch("sys.argv", ["brain-vector", "status"]):
            with patch.object(bv, "_brain_path", return_value=Path("/tmp")):
                bv.main()
                mock_status.assert_called_once()

    @patch.object(bv, "cmd_search")
    def test_main_search(self, mock_search):
        with patch("sys.argv", ["brain-vector", "search", "query", "-k", "10", "--json"]):
            with patch.object(bv, "_brain_path", return_value=Path("/tmp")):
                bv.main()
                mock_search.assert_called_once_with(Path("/tmp"), "query", 10, True)

    @patch.object(bv, "cmd_setup")
    def test_main_setup(self, mock_setup):
        with patch("sys.argv", ["brain-vector", "setup", "--yes"]):
            with patch.object(bv, "_brain_path", return_value=Path("/tmp")):
                bv.main()
                mock_setup.assert_called_once_with(Path("/tmp"), True)

    @patch.object(bv, "cmd_index_rebuild")
    def test_main_index_rebuild(self, mock_rebuild):
        with patch("sys.argv", ["brain-vector", "index", "rebuild"]):
            with patch.object(bv, "_brain_path", return_value=Path("/tmp")):
                bv.main()
                mock_rebuild.assert_called_once_with(Path("/tmp"))
