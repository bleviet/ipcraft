def test_version_exported():
    import ipcraft
    assert hasattr(ipcraft, "__version__")
    assert ipcraft.__version__ == "0.2.0"
