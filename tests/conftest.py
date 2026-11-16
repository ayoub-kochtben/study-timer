import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database


@pytest.fixture
def db_in_tmp(tmp_path):
    return Database(str(tmp_path / "empty.db"))
