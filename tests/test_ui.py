"""Chromium interaction checks using real views and a small LuCI RPC/form fixture.

Install with: python3 -m pip install playwright && python3 -m playwright install chromium
"""
from pathlib import Path
import unittest
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
String.prototype.format = function(...args) {
    let i = 0;
    return this.replace(/%(?:\.(\d+))?([sdf%])/g, (_, precision, kind) => {
        if (kind === '%') return '%';
        const value = args[i++];
        return kind === 'f' ? Number(value).toFixed(Number(precision || 0)) : kind === 'd' ? String(Math.floor(value)) : String(value);
    });
};
window.E = function(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
        if (typeof value === 'function') node.addEventListener(key, value);
        else node.setAttribute(key, value);
    }
    if (children != null) node.append(...(Array.isArray(children) ? children : [children]));
    return node;
};
window.L = { bind: (fn, ctx, ...args) => fn.bind(ctx, ...args) };
window.poll = { callbacks: [], add(fn) { this.callbacks.push(fn); } };
window.ui = {
    createHandlerFn(ctx, method, ...args) { return ev => {
        const target = ev.currentTarget;
        target.disabled = true;
        Promise.resolve((typeof method === 'string' ? ctx[method] : method).call(ctx, ...args, ev))
            .finally(() => { target.disabled = false; });
    }; },
    showModal(title, content) { this.hideModal(); document.body.append(E('div', { id: 'modal' }, [E('h3', {}, title), ...content])); },
    hideModal() { document.querySelector('#modal')?.remove(); },
    addNotification(_, node) { document.body.append(node); },
    awaitReconnect() {}
};
window.fields = {};
window.form = { Map: class {
    constructor(name, title, description) { this.description = description; }
    section() { return { tab() {}, taboption(tab, type, name, label, description) {
        const field = { label, description, value() {} }; fields[name] = field; return field;
    } }; }
    render() { return Promise.resolve(E('form', {}, [
        E('h3', {}, '蜂窝设置'), E('p', {}, this.description || ''),
        ...Object.entries(fields).map(([name, field]) => E('div', {}, [
            E('label', {for: 'setting-' + name}, field.label || name),
            E('input', {id: 'setting-' + name, type: name === 'enabled' ? 'checkbox' : 'text'}),
            E('p', {}, field.description || '')
        ]))
    ])); }
}};
window.fake = {
    release: { tag: 'v-test', url: 'https://github.com/fw', sha256: 'a'.repeat(64), size: 1024, kernel_match: 1, current_kernel: '6.18.60', release_kernel: '6.18.60', same_base: 1 },
    info: { current_tag: 'v1.0.0', current_rev: 'r38253-e2ed57b957' },
    status: { state: 'idle' }, boot: '1', calls: [], fail: '', slowCheck: false,
    modem: { transport: 'usb', present: true, enabled: '1', source: 'daemon', stamp_age: 5, check_interval: 30,
        sim: { phase: 'ready', configured_slot: 'auto', slot: 'esim' }, reg: {},
        signal: { sysmode: 'NR', rsrp_dbm: '-85' }, temp_dc: '730', wwan: { up: true, ip4: '10.0.0.2' } }
};
window.fs = { async exec(path, args = []) {
    const command = args[0] || 'modem'; fake.calls.push(command);
    if (fake.fail === command) throw Error('模拟连接中断');
    let data;
    if (path.endsWith('bootswitch')) {
        if (command === 'to-factory') fake.boot = '0';
        if (command === 'to-openwrt') fake.boot = '1';
        return {code: 0, stdout: `boot_system=${fake.boot} (${fake.boot === '1' ? 'openwrt-second-system' : 'factory-system'})`};
    }
    if (path.endsWith('mt5700-sim')) {
        if (fake.slowSim) await new Promise(resolve => { window.finishSim = resolve; });
        if (fake.simResponse) return fake.simResponse;
        Object.assign(fake.modem.sim, {switch_state:'switching',switch_target:command,switch_error:''});
        return {code:0, stdout:JSON.stringify({started:true,target:command,state:'switching'})};
    }
    if (command === 'modem') {
        if (fake.slowModem) await new Promise(resolve => { window.finishModem = resolve; });
        data = fake.modem;
    }
    if (command === 'check') {
        if (fake.slowCheck) await new Promise(resolve => { window.finishCheck = resolve; });
        data = fake.release;
    }
    if (command === 'status') data = fake.status;
    if (command === 'info') data = fake.info;
    if (command === 'download') data = { started: true };
    if (command === 'preflight') data = { ready: 1 };
    if (command === 'flash') data = { started: true };
    return { code: 0, stdout: JSON.stringify(data) };
}};
window.mount = async function(source) {
    window.current = new Function('view', 'fs', 'ui', 'poll', 'form', 'L', 'E', source)(
        {extend: x => x}, window.fs, window.ui, window.poll, window.form, window.L, window.E);
    document.body.append(await window.current.render(await window.current.load()));
};
'''


@unittest.skipIf(sync_playwright is None, 'Optional Playwright dependency not installed')
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 390, 'height': 844})
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.set_content('<html lang="zh"><body></body></html>')
        self.page.evaluate(HARNESS + '\nvoid 0;')

    def tearDown(self):
        self.assertEqual(self.errors, [])

    def mount(self, name):
        source = (ROOT / f'board/files/www/luci-static/resources/view/nradio/{name}.js').read_text()
        self.page.evaluate('source => mount(source)', source)

    def ethernet_snapshot(self):
        self.page.evaluate("""Object.assign(fake.modem, {
            transport: 'ethernet', source: 'ethernet', link_speed: '2500', carrier_link: 1,
            at_port: '192.168.8.1:20249', netdev: 'wan', temp_dc: '310',
            sim: {phase: 'ready', slot: 'external', configured_slot: '', scichg: '0', state_cn: '已就绪'},
            reg: {operator:'中国联通', cereg_state:'已注册'},
            signal: {sysmode:'NR', rsrp_dbm:'-88', sinr_dc:'210'},
            wwan: {up:true, ip4:'192.168.8.134'},
            traffic: {live_rx:1048576, live_tx:524288, uptime:180}
        })""")

    def test_ethernet_only_exposes_sampling_settings_and_current_counters(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.assertIn('以太网 2500 Mbps', self.page.locator('#mt5700_modem').inner_text())
        self.assertIn('192.168.8.1:20249', self.page.locator('#mt5700_modem').inner_text())
        self.assertIn('31.0 °C', self.page.locator('#mt5700_temp').inner_text())
        self.assertIn('外置 SIM', self.page.locator('#mt5700_sim').inner_text())
        self.assertNotIn('切换', self.page.locator('#mt5700_sim').inner_text())
        self.assertIn('1 个 5G/PoE 上行 + 3 个 LAN', self.page.locator('body').inner_text())
        self.assertIn('IPv4 与 IPv6 共用同一上行口', self.page.locator('body').inner_text())
        self.page.get_by_role('tab', name='流量统计', exact=True).click()
        self.assertIn('WAN 接口当前计数', self.page.locator('#mt5700_sess').inner_text())
        self.assertIn('1.00 MB', self.page.locator('#mt5700_sess').inner_text())
        for selector in ('#mt5700_day', '#mt5700_mon', '#mt5700_tot', '#mt5700_quota'):
            self.assertEqual(self.page.locator(selector).count(), 0)
        self.assertEqual(self.page.get_by_role('button', name='清零', exact=False).count(), 0)
        self.page.get_by_role('tab', name='设置', exact=True).click()
        self.assertEqual(self.page.evaluate('Object.keys(fields).sort()'), ['check_interval', 'enabled'])
        self.assertTrue(self.page.get_by_label('启用状态采样').is_visible())
        self.assertIn('关闭采样不会断开 WAN', self.page.locator('form').inner_text())
        self.assertNotIn('USB', self.page.locator('body').inner_text())
        self.assertNotIn('风扇联动', self.page.locator('body').inner_text())

    def test_ethernet_sim_labels_require_an_explicit_physical_slot(self):
        self.ethernet_snapshot()
        self.mount('modem')
        for slot, label in (('internal', '内置 SIM'), ('external', '外置 SIM')):
            with self.subTest(slot=slot):
                self.page.evaluate('(slot) => { fake.modem.sim.slot = slot; return current.refreshStatus(); }', slot)
                self.assertIn(label, self.page.locator('#mt5700_sim').inner_text())
        for slot in ('sim1', 'sim2', 'esim', '', 'unknown'):
            with self.subTest(slot=slot):
                self.page.evaluate('(slot) => { fake.modem.sim.slot = slot; return current.refreshStatus(); }', slot)
                self.assertEqual(self.page.locator('#mt5700_sim').inner_text(), '当前 SIM 状态：已就绪')
                body = self.page.locator('body').inner_text()
                for unsupported in ('SIM1', 'SIM2', 'eSIM', '自动检测'):
                    self.assertNotIn(unsupported, body)

    def test_sim_switch_confirmation_async_progress_and_completion(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.assertTrue(self.page.get_by_role('button', name='使用外置 SIM', exact=True).is_disabled())
        self.page.get_by_role('button', name='使用内置 SIM', exact=True).click()
        self.assertIn('5G 上行会暂时中断', self.page.locator('#modal').inner_text())
        self.assertIn('同一个物理模组', self.page.locator('#modal').inner_text())
        self.assertIn('配置文件仍各自独立', self.page.locator('#modal').inner_text())
        self.page.get_by_role('button', name='取消', exact=True).click()
        self.assertEqual(self.page.evaluate("fake.calls.filter(x => x === 'internal').length"), 0)
        self.page.get_by_role('button', name='使用内置 SIM', exact=True).click()
        self.page.evaluate('fake.slowSim = true')
        self.page.get_by_role('button', name='确认切换至内置 SIM', exact=True).click()
        self.assertIn('正在提交', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='使用内置 SIM', exact=True).is_disabled())
        self.page.evaluate("current.doSimSwitch('internal')")
        self.assertEqual(self.page.evaluate("fake.calls.filter(x => x === 'internal').length"), 1)
        self.page.evaluate('fake.slowSim = false; finishSim()')
        self.page.wait_for_function('!current.simRequestPending && !current.refreshing')
        self.assertIn('正在切换至内置 SIM', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='使用外置 SIM', exact=True).is_disabled())
        self.page.evaluate("""() => {
            Object.assign(fake.modem.sim, {switch_state:'done',switch_target:'internal',slot:'internal'});
            fake.modem.wwan = {up:false};
            return current.refreshStatus();
        }""")
        self.assertIn('已确认使用内置 SIM', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertIn('是否已联网', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertNotIn('已连接', self.page.locator('#mt5700_wwan').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='使用内置 SIM', exact=True).is_disabled())
        self.assertTrue(self.page.get_by_role('button', name='使用外置 SIM', exact=True).is_enabled())
        self.page.evaluate("current.doSimSwitch('internal')")
        self.assertEqual(self.page.evaluate("fake.calls.filter(x => x === 'internal').length"), 1)

    def test_sim_switch_command_failure_and_background_failure_are_visible(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.page.evaluate("fake.simResponse = {code:1,stderr:'AT 通道忙'}")
        self.page.get_by_role('button', name='使用内置 SIM', exact=True).click()
        self.page.get_by_role('button', name='确认切换至内置 SIM', exact=True).click()
        self.page.wait_for_function('!current.simRequestPending && !current.refreshing')
        self.assertIn('切换失败：AT 通道忙', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='使用内置 SIM', exact=True).is_enabled())
        self.page.evaluate('fake.simResponse = null')
        self.page.get_by_role('button', name='使用内置 SIM', exact=True).click()
        self.page.get_by_role('button', name='确认切换至内置 SIM', exact=True).click()
        self.page.wait_for_function('!current.simRequestPending && !current.refreshing')
        self.page.evaluate("""() => {
            Object.assign(fake.modem.sim, {switch_state:'error',switch_target:'internal',switch_error:'卡槽读回未确认'});
            return current.refreshStatus();
        }""")
        self.assertIn('卡槽读回未确认', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertNotIn('正在切换', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='使用内置 SIM', exact=True).is_enabled())

    def test_sim_switch_same_target_reply_does_not_wait_forever(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.page.evaluate("fake.simResponse = {code:0,stdout:JSON.stringify({started:false,state:'done',target:'internal'})}")
        self.page.get_by_role('button', name='使用内置 SIM', exact=True).click()
        self.page.evaluate("""Object.assign(fake.modem.sim, {
            slot:'internal',switch_state:'done',switch_target:'internal'
        })""")
        self.page.get_by_role('button', name='确认切换至内置 SIM', exact=True).click()
        self.page.wait_for_function('!current.simRequestPending && !current.refreshing')
        self.assertIn('已确认使用内置 SIM', self.page.locator('#mt5700_sim_switch').inner_text())
        self.assertIsNone(self.page.evaluate('current.simSwitchPending'))
        self.assertTrue(self.page.get_by_role('button', name='使用外置 SIM', exact=True).is_enabled())

    def test_ethernet_wan_and_at_failures_are_distinct(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.page.evaluate("fake.modem.present = false; current.refreshStatus()")
        self.assertIn('AT 状态接口暂未响应', self.page.locator('.nr-md-banner').inner_text())
        self.assertIn('已连接', self.page.locator('#mt5700_wwan').inner_text())
        self.assertNotIn('未检测到 SIM', self.page.locator('body').inner_text())
        self.page.evaluate("fake.modem.carrier_link = 0; current.refreshStatus()")
        self.assertIn('WAN 网口链路已断开', self.page.locator('.nr-md-banner').inner_text())
        self.assertNotIn('已连接', self.page.locator('#mt5700_wwan').inner_text())
        self.page.evaluate("fake.modem.carrier_link = 1; fake.modem.enabled = '0'; current.refreshStatus()")
        self.assertIn('状态采样已关闭', self.page.locator('.nr-md-banner').inner_text())
        self.assertIn('已连接', self.page.locator('#mt5700_wwan').inner_text())

    def test_ethernet_refresh_preserves_snapshot_and_reports_sample_age(self):
        self.ethernet_snapshot()
        self.mount('modem')
        self.page.evaluate('fake.slowModem = true')
        self.page.get_by_role('button', name='刷新状态', exact=True).click()
        self.assertTrue(self.page.get_by_role('button', name='刷新中…', exact=True).is_disabled())
        self.assertIn('31.0 °C', self.page.locator('#mt5700_temp').inner_text())
        self.assertIn('5 秒前', self.page.locator('#mt5700_meta').inner_text())
        self.page.evaluate("fake.slowModem = false; fake.modem.sample_error = '连接超时'; finishModem()")
        self.page.wait_for_function('!current.refreshing')
        self.assertIn('当前显示 5 秒前的数据', self.page.locator('.nr-md-banner').inner_text())
        self.assertIn('31.0 °C', self.page.locator('#mt5700_temp').inner_text())
        self.page.evaluate('fake.modem.stamp_age = 120; fake.modem.present = false; current.refreshStatus()')
        self.assertEqual(self.page.locator('#mt5700_temp').inner_text(), '—')
        self.assertIn('数据已过期', self.page.locator('#mt5700_meta').inner_text())
        self.assertIn('已连接', self.page.locator('#mt5700_wwan').inner_text())

    def test_ethernet_missing_counters_are_unknown_and_tabs_work_with_keyboard(self):
        self.ethernet_snapshot()
        self.page.evaluate('delete fake.modem.traffic.live_rx; delete fake.modem.traffic.live_tx')
        self.mount('modem')
        tab = self.page.get_by_role('tab', name='总览', exact=True)
        tab.focus()
        self.page.keyboard.press('ArrowRight')
        self.assertEqual(self.page.get_by_role('tab', name='小区与信号', exact=True).get_attribute('aria-selected'), 'true')
        self.page.keyboard.press('End')
        self.assertTrue(self.page.locator('form').is_visible())
        for width in (1440, 390):
            self.page.set_viewport_size({'width': width, 'height': 900})
            for title in ('总览', '小区与信号', 'SIM 与 QoS', '流量统计', '设置'):
                self.page.get_by_role('tab', name=title, exact=True).click()
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)
        self.page.get_by_role('tab', name='流量统计', exact=True).click()
        self.assertNotIn('0 B', self.page.locator('#mt5700_sess').inner_text())
        self.assertEqual(self.page.locator('#mt5700_raterx').inner_text(), '等待采样')

    def test_upgrade_renders_before_network_check_finishes(self):
        self.page.evaluate('fake.slowCheck = true')
        self.mount('upgrade')
        self.assertTrue(self.page.get_by_role('heading', name='在线固件更新', exact=True).is_visible())
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_disabled())
        installed = self.page.get_by_role('row').filter(has=self.page.get_by_role('rowheader', name='当前固件'))
        baseline = self.page.get_by_role('row').filter(has=self.page.get_by_role('rowheader', name='当前 OpenWrt 基线'))
        self.assertEqual(installed.get_by_role('cell').inner_text(), 'v1.0.0')
        self.assertIn('r38253-e2ed57b957', baseline.get_by_role('cell').inner_text())
        self.page.evaluate('finishCheck()')
        self.page.wait_for_function('!current.checking')
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_enabled())

    def test_system_views_center_in_the_available_content_width(self):
        for view, selector in (('bootswitch', '.nr-bs'), ('upgrade', '.nr-up')):
            with self.subTest(view=view):
                self.mount(view)
                content = self.page.locator(selector)
                for viewport_width in (1440, 390):
                    self.page.set_viewport_size({'width': viewport_width, 'height': 844})
                    bounds = content.bounding_box()
                    self.assertAlmostEqual(bounds['x'] + bounds['width'] / 2, viewport_width / 2, delta=1)
                    self.assertEqual(self.page.evaluate('document.documentElement.scrollWidth'), viewport_width)
                content.evaluate('node => node.remove()')

    def test_download_restore_progress_rpc_error_and_completion(self):
        self.page.evaluate("fake.status = {state: 'downloading', bytes: 512, total: 1024, tag: 'v-old'}")
        self.mount('upgrade')
        self.assertEqual(self.page.get_by_role('progressbar').get_attribute('aria-valuenow'), '50')
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_disabled())
        self.page.evaluate("fake.fail = 'status'; current.refreshDownload()")
        self.assertIn('自动重试', self.page.locator('body').inner_text())
        self.page.evaluate("fake.fail = ''; fake.status = {state: 'done', have_image: true, tag: 'v-old', sha256: 'a'.repeat(64)}; current.refreshDownload()")
        self.assertIn('固件已就绪：v-old', self.page.locator('body').inner_text())
        self.page.get_by_role('button', name='清除配置升级', exact=True).click()
        self.page.wait_for_selector('#modal')
        self.assertIn('v-old', self.page.locator('#modal').inner_text())
        self.assertIn('192.168.1.1', self.page.locator('#modal').inner_text())

    def test_started_download_keeps_button_disabled(self):
        self.mount('upgrade')
        self.page.wait_for_function('!current.checking')
        self.page.evaluate("fake.status = {state:'downloading',bytes:100,total:1024,tag:'test'}")
        self.page.get_by_role('button', name='下载固件到路由器').click()
        self.page.wait_for_function('!current.busy')
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_disabled())
        self.assertTrue(self.page.get_by_role('button', name='重新检查').is_disabled())

    def test_kernel_mismatch_allows_download_with_warning(self):
        self.mount('upgrade')
        self.page.wait_for_function('!current.checking')
        # NBCPE sysupgrade refreshes kernel_2nd too, so a kernel-mismatched
        # release stays downloadable; only an informational banner is shown.
        self.page.evaluate('(match) => { fake.release.kernel_match = match; return current.handleCheck(true); }', 0)
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_enabled())
        self.assertIn('跨内核版本提示', self.page.locator('body').inner_text())
        self.assertIn('kernel_2nd 与 rootfs_2nd', self.page.locator('body').inner_text())
        # Unknown remote kernel: no banner, still downloadable
        self.page.evaluate('(match) => { fake.release.kernel_match = match; return current.handleCheck(true); }', -1)
        self.assertNotIn('跨内核版本提示', self.page.locator('body').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_enabled())
        self.page.evaluate("fake.fail = 'check'; current.handleCheck(true)")
        self.assertTrue(self.page.get_by_role('button', name='重新检查').is_enabled())
        self.assertIn('重试', self.page.locator('body').inner_text())

    def test_download_start_error_and_flash_error_are_visible(self):
        self.mount('upgrade')
        self.page.wait_for_function('!current.checking')
        self.page.evaluate("fake.fail = 'download'; current.handleDownload()")
        self.assertIn('模拟连接中断', self.page.locator('body').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='下载固件到路由器').is_enabled())
        self.page.evaluate("fake.fail = 'flash'; current.renderDownload({state:'done',have_image:true,tag:'test',sha256:'a'.repeat(64)}); current.doFlash(false, 'a'.repeat(64))")
        self.assertFalse(self.page.locator('#modal').count())
        self.assertTrue(self.page.get_by_role('button', name='保留配置升级', exact=True).is_enabled())

    def test_modem_stale_temperature_and_query_failure(self):
        self.mount('modem')
        self.assertIn('73.0', self.page.locator('#mt5700_temp').inner_text())
        self.page.evaluate('fake.modem.stamp_age = 90; current.refreshStatus()')
        self.assertEqual(self.page.locator('#mt5700_temp').inner_text(), '—')
        self.page.evaluate("fake.fail = 'modem'; current.refreshStatus()")
        self.assertNotIn('已连接', self.page.locator('#mt5700_wwan').inner_text())
        self.assertIn('自动重试', self.page.locator('#mt5700_meta').inner_text())
        self.assertEqual(self.page.locator('#mt5700_meta').count(), 1)
        self.assertTrue(self.page.evaluate("fields.apn.validate('', '3gnet') === true"))
        self.assertTrue(self.page.evaluate("typeof fields.apn.validate('', 'bad\\\"apn') === 'string'"))

    def test_modem_bad_first_response_still_renders_settings(self):
        self.page.evaluate("fake.fail = 'modem'")
        self.mount('modem')
        self.page.get_by_text('设置', exact=True).click()
        self.assertTrue(self.page.locator('form').is_visible())
        self.assertEqual(self.page.evaluate('Object.keys(fields).sort()'), ['check_interval', 'enabled'])
        self.assertIn('自动重试', self.page.locator('#mt5700_meta').inner_text())
        self.page.evaluate("fake.fail = ''; fake.modem.enabled = '0'; current.refreshStatus()")
        self.assertIn('已关闭', self.page.locator('#mt5700_modem').inner_text())

    def test_new_cellular_tabs_quota_and_qos_survive_merge(self):
        self.page.evaluate("""Object.assign(fake.modem, {
            qos: {qci:'9',dl_ambr_kbps:'100000',ul_ambr_kbps:'50000',apn:'3gnet'},
            pdp: {addr4:'10.0.0.2'},
            traffic: {mon_rx:104857600,mon_tx:0,limit_mb:200,reset_day:15}
        })""")
        self.mount('modem')
        self.page.get_by_text('SIM 与 QoS', exact=True).click()
        self.assertIn('QCI/5QI 9', self.page.locator('#mt5700_qci').inner_text())
        self.assertIn('100', self.page.locator('#mt5700_ambrdl').inner_text())
        self.page.evaluate('fake.modem.stamp_age = 90; current.refreshStatus()')
        self.assertEqual(self.page.locator('#mt5700_ambrdl').inner_text(), '—')
        self.assertEqual(self.page.locator('#mt5700_pdp4').inner_text(), '—')
        self.page.get_by_text('流量统计', exact=True).click()
        self.assertIn('50%', self.page.locator('#mt5700_quota').inner_text())
        self.page.get_by_text('设置', exact=True).click()
        self.assertTrue(self.page.evaluate('!!fields.netmode && !!fields.traffic_limit_mb && !!fields.traffic_reset_day && !!fields.traffic_action'))

    def test_pending_boot_target_has_reboot_and_cancel_actions(self):
        self.page.evaluate("fake.boot = '0'")
        self.mount('bootswitch')
        self.assertIn('下次重启进入', self.page.locator('body').inner_text())
        self.assertTrue(self.page.get_by_role('button', name='立即重启进入原厂系统…').is_visible())
        self.page.get_by_role('button', name='取消切换，保持 OpenWrt').click()
        self.page.get_by_role('button', name='切换到原厂系统…').wait_for()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)

    def test_modem_privacy_mask_band_inference_and_mobile_layout(self):
        self.page.evaluate("""Object.assign(fake.modem, {
            usb_speed: '480',
            imei: '864920061940318',
            sim: { phase: 'ready', state_cn: '已就绪', configured_slot: 'auto', slot: 'sim1',
                   imsi: '460010928378821', iccid: '89860123801190284910', carrier: '中国联通' },
            signal: { sysmode: 'NR', rsrp_dbm: '-81', sinr_dc: '195', rsrq_dc: '-95' },
            cell: { rat: 'NR', raw: '460,01,627264,1,1A2B3C01,312,3104,-81,-9,-19' }
        })""")
        self.mount('modem')
        self.assertIn('USB 2.0', self.page.locator('.nr-md-banner').inner_text())
        self.assertIn('46001******8821', self.page.locator('#mt5700_imsi').inner_text())
        self.assertNotIn('460010928378821', self.page.locator('#mt5700_imsi').inner_text())
        self.page.get_by_role('button', name='显示完整标识').click()
        self.assertIn('460010928378821', self.page.locator('#mt5700_imsi').inner_text())
        self.assertIn('864920061940318', self.page.locator('#mt5700_imei').inner_text())
        self.page.evaluate("""() => {
            Object.defineProperty(navigator, 'clipboard', {value: undefined});
            document.execCommand = command => {
                window.copied = document.activeElement.value;
                return command === 'copy';
            };
        }""")
        imsi = self.page.locator('#mt5700_imsi .nr-md-copychip').filter(has_text='IMSI:')
        imsi.get_by_role('button', name='复制', exact=True).click()
        self.assertEqual(self.page.evaluate('window.copied'), '460010928378821')
        self.assertIn('已复制', imsi.get_by_role('status').inner_text())
        self.page.get_by_role('button', name='隐藏敏感标识').click()
        self.assertNotIn('460010928378821', self.page.locator('#mt5700_imsi').inner_text())

        for tab in ('总览', '小区与信号', 'SIM 与 QoS', '流量统计', '设置'):
            self.page.get_by_role('tab', name=tab, exact=True).click()
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)

        self.page.get_by_role('tab', name='小区与信号', exact=True).click()
        self.assertIn('Band n78 (3.5 GHz TDD)', self.page.locator('#mt5700_cellrat').inner_text())
        self.assertIn('30 kHz', self.page.locator('#mt5700_celltable').inner_text())
        self.assertIn('0x1A2B3C01', self.page.locator('#mt5700_celltable').inner_text())

    def test_upgrade_presets_and_mobile_layout(self):
        self.page.evaluate("fake.fail = 'check'; void 0;")
        self.mount('upgrade')
        self.page.wait_for_function('!current.checking')
        self.assertIn('v1.0.0', self.page.locator('body').inner_text())
        self.assertIn('r38253-e2ed57b957', self.page.locator('body').inner_text())
        self.assertIn('检查失败', self.page.locator('body').inner_text())
        self.assertIn('暂未获取远端版本', self.page.locator('body').inner_text())
        self.assertEqual(
            self.page.get_by_role('link', name='本地上传 / 备份').get_attribute('href'),
            '/cgi-bin/luci/admin/system/flash'
        )
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)

        self.page.evaluate("""() => {
            fake.fail = '';
            Object.assign(fake.release, {
                tag: 'v1.0.0',
                rev: 'r38253-e2ed57b957',
                same_base: 1,
                kernel_match: 1,
                sha256: 'f0854d139c4a2e8b0d112233445566778899aabbccddeeff0011223344815770',
                notes: '## 更新重点\\n- 优化在线固件更新中心'
            });
            return current.handleCheck(true);
        }""")
        self.assertIn('当前已是最新', self.page.locator('body').inner_text())
        self.assertIn('f0854d139c…44815770', self.page.locator('body').inner_text())
        self.page.get_by_role('button', name='展开更新日志').click()
        self.assertIn('优化在线固件更新中心', self.page.locator('body').inner_text())
        self.page.get_by_role('button', name='收起更新日志').click()

        self.page.get_by_role('button', name='ghfast 加速源').click()
        self.assertEqual(self.page.get_by_label('下载加速前缀（可选）').input_value(), 'https://ghfast.top/')
        self.page.get_by_role('button', name='加速镜像示例').click()
        self.assertEqual(self.page.get_by_label('下载加速前缀（可选）').input_value(), 'https://gh-proxy.com/')
        self.page.get_by_role('button', name='GitHub 官方直连').click()
        self.assertEqual(self.page.get_by_label('下载加速前缀（可选）').input_value(), '')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)


if __name__ == '__main__':
    unittest.main()
