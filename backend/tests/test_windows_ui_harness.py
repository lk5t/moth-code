"""Native test helper contracts; these fixtures do not claim Windows execution."""
from pathlib import Path
import runpy
from types import SimpleNamespace


def test_late_introduction_is_skipped_before_settings(monkeypatch):
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    UI=module['WindowsUI'];ui=object.__new__(UI);actions=[]
    skip='Continue without signing in (editor, terminal and Git work offline)'
    def button(name):return SimpleNamespace(element_info=SimpleNamespace(name=name),is_visible=lambda:True,is_enabled=lambda:True)
    import itertools
    trees=itertools.chain([[],[],[button(skip)]],itertools.repeat([button('Settings')]))
    ui.root=SimpleNamespace(descendants=lambda **kw:next(trees))
    ui.click=lambda name,**kw:actions.append(name)
    clock=[0.0]
    monkeypatch.setattr(module['time'],'sleep',lambda s:clock.__setitem__(0,clock[0]+s))
    monkeypatch.setattr(module['time'],'monotonic',lambda:clock[0])
    ui.await_workspace()
    assert actions==[skip]


def test_introduction_opening_after_settings_appeared_is_still_skipped(monkeypatch):
    """The 0.6.2 release run: Settings rendered first, then the welcome dialog covered it."""
    import itertools
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    UI=module['WindowsUI'];ui=object.__new__(UI);actions=[]
    skip='Continue without signing in (editor, terminal and Git work offline)'
    def button(name):return SimpleNamespace(element_info=SimpleNamespace(name=name),is_visible=lambda:True,is_enabled=lambda:True)
    trees=itertools.chain([[button('Settings')],[button('Settings')],[button(skip)]],itertools.repeat([button('Settings')]))
    ui.root=SimpleNamespace(descendants=lambda **kw:next(trees))
    ui.click=lambda name,**kw:actions.append(name)
    clock=[0.0]
    monkeypatch.setattr(module['time'],'sleep',lambda s:clock.__setitem__(0,clock[0]+s))
    monkeypatch.setattr(module['time'],'monotonic',lambda:clock[0])
    ui.await_workspace()
    assert actions==[skip]


def test_existing_installs_need_no_introduction(monkeypatch):
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    ui=object.__new__(module['WindowsUI'])
    ui.root=SimpleNamespace(descendants=lambda **kw:[SimpleNamespace(element_info=SimpleNamespace(name='Settings'),is_visible=lambda:True,is_enabled=lambda:True)])
    ui.click=lambda *args,**kw:(_ for _ in ()).throw(AssertionError('Existing installs must not click a nonexistent intro'))
    clock=[0.0]
    monkeypatch.setattr(module['time'],'sleep',lambda s:clock.__setitem__(0,clock[0]+s))
    monkeypatch.setattr(module['time'],'monotonic',lambda:clock[0])
    ui.await_workspace()


def test_published_key_check_does_not_require_local_git_tags(monkeypatch):
    import base64,json
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/test-published-desktop-update.py'))
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps({'encoding':'base64','content':base64.b64encode(b'pinned-public-key\n').decode()}).encode())
    monkeypatch.setattr(module['subprocess'],'run',run)
    assert module['published_updater_key']('0.5.9')==b'pinned-public-key'
    assert calls==[('gh','api','repos/lk5t/moth-code/contents/app/src-tauri/updater.pub?ref=desktop-v0.5.9')]


def test_draft_targets_composer_instead_of_conversation_search():
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    ui=object.__new__(module['WindowsUI'])
    def edit(name,value):
        field=SimpleNamespace(CurrentValue=value)
        field.SetValue=lambda text:setattr(field,'CurrentValue',text)
        return SimpleNamespace(element_info=SimpleNamespace(name=name),iface_value=field,is_visible=lambda:True,is_enabled=lambda:True)
    search=edit('Search conversations','search unchanged');composer=edit('Message MOTH','')
    ui.root=SimpleNamespace(descendants=lambda **kw:[search,composer])
    ui.draft('synthetic unsent draft')
    assert ui.draft()=='synthetic unsent draft'
    assert search.iface_value.CurrentValue=='search unchanged'


def test_tab_that_renders_late_is_still_selected(monkeypatch):
    """0.6.2 release run: Settings rendered its tabs after the first look, and a remembered tab showed."""
    import itertools
    module=runpy.run_path(str(Path(__file__).resolve().parents[2]/'scripts/windows-desktop-ui.py'))
    ui=object.__new__(module['WindowsUI']);clicked=[]
    tab=SimpleNamespace(element_info=SimpleNamespace(name='Account',control_type='TabItem'))
    trees=itertools.chain([[],[]],itertools.repeat([tab]))
    ui.root=SimpleNamespace(descendants=lambda **kw:next(trees))
    ui.click=lambda name,**kw:clicked.append((name,kw.get('control_type')))
    clock=[0.0]
    monkeypatch.setattr(module['time'],'sleep',lambda s:clock.__setitem__(0,clock[0]+s))
    monkeypatch.setattr(module['time'],'monotonic',lambda:clock[0])
    assert ui.optional_tab('Account') is True and clicked==[('Account','TabItem')]
    ui.root=SimpleNamespace(descendants=lambda **kw:[])  # a single-page Settings (0.5.1) never has tabs
    assert ui.optional_tab('Account') is False
