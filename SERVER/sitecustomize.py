"""Project-wide Python startup tweaks.

When Python starts from this project root, it imports this module automatically.
Bytecode caches are collected under one project-level .pycache directory.
----
프로젝트 전반에 적용되는 파이썬 시작 시점의 조정(Tweak) 사항입니다.
이 프로젝트의 루트(최상위 폴더)에서 파이썬이 시작될 때, 이 모듈을 자동으로 임포트합니다.
바이트코드 캐시(Bytecode caches)는 프로젝트 레벨의 단일 .pycache 디렉터리 아래에 모여 저장됩니다
"""

from pathlib import Path
import sys

# py_compile을 직접 실행할 때는 아래처럼 실행해야 캐시가 흩어지지 않습니다:
# PYTHONPYCACHEPREFIX=.pycache python3 -m py_compile <files>
sys.pycache_prefix = str(Path(__file__).resolve().parent / ".pycache")
