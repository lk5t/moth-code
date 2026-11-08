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
        types = (control_type,) if control_type else ('Button', 'TabItem', 'CheckBox', 'RadioButton', 'Hyperlink', 'Custom')
        c = self.find(name, types, timeout)
        try:
            c.iface_scroll_item.ScrollIntoView()
        except Exception:
            pass
        if c.element_info.control_type == 'TabItem':
            c.iface_selection_item.Select()
        elif c.element_info.control_type == 'CheckBox':
            c.iface_toggle.Toggle()
        else:
            c.iface_invoke.Invoke()

    def set_text(self, name, value):
        self.find(name, ('Edit',)).iface_value.SetValue(value)

    def text_value(self, name):
        return self.find(name, ('Edit',)).iface_value.CurrentValue

    def configure_cloud(self, url):
        try:
            self.click('Continue without signing in (editor, terminal and Git work offline)', timeout=2)
        except AssertionError:
            pass
        self.click('Settings')
        self.click('Account', control_type='TabItem')
        self.set_text('MOTH Cloud server address', url)
        self.click('Test & use')
        self.find('Connected to MOTH Cloud', ('Text',), prefix=True)

    def check_update(self):
        self.click('Settings')
        self.click('Updates & about')
        self.click('Check now')

    def close(self):
        self.root.close()
