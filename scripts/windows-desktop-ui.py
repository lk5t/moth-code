"""Windows-only accessibility driver for the unchanged, signed desktop executable.

Uses UI Automation patterns, not release DevTools/debugging flags. No application
credentials or edit values are included in failure diagnostics.
"""
import time


class WindowsUI:
    def __init__(self, pid, timeout=120):
        from pywinauto import Desktop
        self.window = Desktop(backend='uia').window(process=pid, title='MOTH Code')
        self.window.wait('exists', timeout=timeout)
        self.root = self.window.wrapper_object()

    def find(self, name, types=None, timeout=60, prefix=False):
        deadline = time.monotonic() + timeout
        while True:
            for c in self.root.descendants():
                info = c.element_info
                if types and info.control_type not in types:
                    continue
                if (info.name.startswith(name) if prefix else info.name == name) and c.is_enabled():
                    return c
            if time.monotonic() > deadline:
                labels = [(c.element_info.control_type, c.element_info.name) for c in self.root.descendants()
                          if c.element_info.control_type in ('Button', 'TabItem', 'Window', 'Text')][:60]
                raise AssertionError(f'Windows control unavailable: {name}; controls={labels}')
            time.sleep(1)

    def click(self, name, timeout=60, control_type=None):
        from pywinauto.uia_defines import NoPatternInterfaceError
        types = (control_type,) if control_type else ('Button', 'TabItem', 'CheckBox', 'RadioButton', 'Hyperlink', 'Custom')
        c = self.find(name, types, timeout)
        try:
            c.iface_scroll_item.ScrollIntoView()
        except Exception:
            pass
        actions = [('iface_selection_item', 'Select'), ('iface_invoke', 'Invoke')] if c.element_info.control_type == 'TabItem' else [
            ('iface_invoke', 'Invoke'), ('iface_toggle', 'Toggle')]
        for pattern, action in actions:
            try:
                getattr(getattr(c, pattern), action)()
                return
            except NoPatternInterfaceError:
                pass
        raise AssertionError(f'Windows control has no supported action: {name}')

    def optional_tab(self, name):
        # The published 0.5.1 installer has one Settings page; newer versions group it in tabs.
        if any(c.element_info.name == name and c.element_info.control_type == 'TabItem'
               for c in self.root.descendants()):
            self.click(name, control_type='TabItem')

    def field(self, name):
        for c in self.root.descendants(control_type='Edit'):
            if c.element_info.name == name:
                return c
        edits = [c for c in self.root.descendants(control_type='Edit') if c.is_visible() and c.is_enabled()]
        if len(edits) == 1:
            return edits[0]  # legacy single-page Settings has one server-address editor
        return self.find(name, ('Edit',))

    def set_text(self, name, value):
        self.field(name).iface_value.SetValue(value)

    def text_value(self, name):
        return self.field(name).iface_value.CurrentValue

    def configure_cloud(self, url):
        try:
            self.click('Continue without signing in (editor, terminal and Git work offline)', timeout=2)
        except AssertionError:
            pass
        self.click('Settings')
        self.optional_tab('Account')
        self.set_text('MOTH Cloud server address', url)
        self.click('Test & use')
        self.find('Connected', ('Text',), prefix=True)

    def check_update(self):
        self.click('Settings')
        self.optional_tab('Updates & about')
        self.click('Check now')

    def close(self):
        self.root.close()
