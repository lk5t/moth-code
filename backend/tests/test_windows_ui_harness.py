"""Driver startup ordering, with an accessibility-tree fixture rather than a Windows claim."""
from pathlib import Path
import runpy
from types import SimpleNamespace


def test_late_introduction_is_skipped_before_settings(monkeypatch):
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    UI=module['WindowsUI'];ui=object.__new__(UI);actions=[]
    skip='Continue without signing in (editor, terminal and Git work offline)'
    def button(name):return SimpleNamespace(element_info=SimpleNamespace(name=name),is_visible=lambda:True,is_enabled=lambda:True)
    trees=iter([[],[],[button(skip)],[button('Settings')]])
    ui.root=SimpleNamespace(descendants=lambda **kw:next(trees))
    ui.click=lambda name,**kw:actions.append(name)
    monkeypatch.setattr(module['time'],'sleep',lambda _:None)
    ui.await_workspace()
    assert actions==[skip]


def test_existing_installs_need_no_introduction(monkeypatch):
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    ui=object.__new__(module['WindowsUI'])
    ui.root=SimpleNamespace(descendants=lambda **kw:[SimpleNamespace(element_info=SimpleNamespace(name='Settings'),is_visible=lambda:True,is_enabled=lambda:True)])
    ui.click=lambda *args,**kw:(_ for _ in ()).throw(AssertionError('Existing installs must not click a nonexistent intro'))
    ui.await_workspace()
