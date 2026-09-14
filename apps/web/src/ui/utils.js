export function dateKey(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; }
export function zonedParts(value, zone = 'Asia/Hong_Kong') {
    const parts = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(value));
    const o = Object.fromEntries(parts.map(p => [p.type, p.value]));
    return { date: `${o.year}-${o.month}-${o.day}`, time: `${o.hour}:${o.minute}` };
}
export function wallTimeToISO(date, time, zone = 'Asia/Hong_Kong') {
    const target = new Date(`${date}T${time}:00Z`).getTime();
    let guess = target;
    for (let i = 0; i < 3; i++) {
        const p = zonedParts(guess, zone);
        const seen = new Date(`${p.date}T${p.time}:00Z`).getTime();
        guess += target - seen;
    }
    const check = zonedParts(guess, zone);
    if (check.date !== date || check.time !== time)
        throw new Error('这个本地时间不存在，请检查夏令时与日期。');
    return new Date(guess).toISOString();
}
export function formatBytes(n) { return n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`; }
export function formatTime(x) { return new Date(x).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
export function route() { const parts = decodeURI(location.hash.replace(/^#\/?/, '')).split('/'); return { page: parts[0] || 'dashboard', cid: parts[1] || '', tab: parts[2] || 'learn' }; }
export function goto(path) { location.hash = '#/' + path; }
