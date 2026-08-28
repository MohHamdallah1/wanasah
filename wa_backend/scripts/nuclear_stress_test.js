import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import { randomIntBetween } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';
import { Counter } from 'k6/metrics'; // +++ استدعاء العداد الصارم +++

export const shieldHits = new Counter('shield_hits'); // +++ تعريف العداد +++

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:9090'; 
const NUM_DRIVERS = parseInt(__ENV.NUM_DRIVERS || '60');
const NUM_ADMINS = parseInt(__ENV.NUM_ADMINS || '5');
// +++ تم التخفيض لـ 200 ليتناسب مع قدرات الجهاز المحلي (Localhost Limits) +++
const TARGET_VUS = parseInt(__ENV.TARGET_VUS || '2000'); 

export const options = {
    scenarios: {
        browsing: {
            executor: 'ramping-vus',
            exec: 'browseFn',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.floor(TARGET_VUS * 0.5) },
                { duration: '1m',  target: TARGET_VUS },
                { duration: '30s', target: 0 },
            ],
        },
        login_storm: {
            executor: 'ramping-vus',
            exec: 'loginStormFn',
            startVUs: 0,
            stages: [
                { duration: '30s', target: Math.max(10, Math.floor(TARGET_VUS * 0.1)) },
                { duration: '1m',  target: Math.max(20, Math.floor(TARGET_VUS * 0.2)) },
                { duration: '30s', target: 0 },
            ],
            startTime: '10s',
        },
    },
    thresholds: {
        'http_req_failed': ['rate<0.05'], // نسبة الفشل العامة
        // +++ إصلاح الـ Tags حسب توجيهات البوت لتسجيل الزمن الفعلي +++
        'http_req_duration{my_route:dashboard}':  ['p(95)<3000'],
        'http_req_duration{my_route:catalog}':    ['p(95)<2000'],
        'http_req_duration{my_route:inventory}':  ['p(95)<5000'],
        'http_req_duration{my_route:ledger}':     ['p(95)<4000'],
        'http_req_duration{my_route:login_driver}': ['p(95)<4000'],
        // +++ إصلاح عتبة الـ 429 لتقرأ من الـ Checks مباشرة +++
        'shield_hits': ['count>5'], // +++ إجبار السكربت على الفشل الحتمي (Fail) إذا لم يصد الدرع 5 هجمات على الأقل +++ 
    },
};

export function setup() {
    const pingRes = http.get(`${BASE_URL}/`);
    if (pingRes.status !== 200 || !pingRes.body.includes("Wanasah")) {
        fail(`[FATAL] Server mismatch or down! Check Uvicorn on 9090. Target returned: ${pingRes.status}`);
    }

    const driverTokens = [];
    const adminTokens = [];
    let driverFails = 0;

    console.log(`[SETUP] Authenticating ${NUM_DRIVERS} drivers...`);
    for (let i = 1; i <= NUM_DRIVERS; i++) {
        const res = http.post(`${BASE_URL}/driver/login`,
            JSON.stringify({ username: `driver_test_${i}`, password: 'Driver1234!' }),
            { headers: { 'Content-Type': 'application/json' } });
        
        if (res.status === 200 && res.json('token')) {
            driverTokens.push(res.json('token'));
        } else {
            driverFails++;
        }
        sleep(0.02); 
    }

    console.log(`[SETUP] Authenticating ${NUM_ADMINS} admins...`);
    for (let i = 1; i <= NUM_ADMINS; i++) {
        let res = http.post(`${BASE_URL}/auth/login`,
            JSON.stringify({ username: `admin_test_${i}`, password: 'Admin1234!' }),
            { headers: { 'Content-Type': 'application/json' } });
        
        if (res.status === 404) {
            res = http.post(`${BASE_URL}/login`,
                JSON.stringify({ username: `admin_test_${i}`, password: 'Admin1234!' }),
                { headers: { 'Content-Type': 'application/json' } });
        }

        if (res.status === 200 && res.json('token')) {
            adminTokens.push(res.json('token'));
        }
        sleep(0.02);
    }

    if (driverTokens.length === 0) {
        fail(`[FATAL] No driver could login. Check DB or brute-force blocks.`);
    }

    console.log(`[READY] Got ${driverTokens.length} Driver Tokens & ${adminTokens.length} Admin Tokens.`);
    return { driverTokens, adminTokens };
}

export function browseFn(data) {
    const token = data.driverTokens[Math.floor(Math.random() * data.driverTokens.length)];
    const authHeaders = {
        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    };

    // +++ ربط الـ Tags بشكل صحيح للقياس +++
    const dashRes = http.get(`${BASE_URL}/driver/dashboard`, Object.assign({}, authHeaders, { tags: { my_route: 'dashboard' } }));
    check(dashRes, { 'dashboard 200': (r) => r.status === 200 });

    const catRes = http.get(`${BASE_URL}/product_variants`, Object.assign({}, authHeaders, { tags: { my_route: 'catalog' } }));
    check(catRes, { 'catalog 200': (r) => r.status === 200 });

    if (data.adminTokens.length > 0 && Math.random() < 0.2) {
        const adminToken = data.adminTokens[Math.floor(Math.random() * data.adminTokens.length)];
        const adminHeaders = {
            headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
        };

        http.get(`${BASE_URL}/warehouse/inventory`, Object.assign({}, adminHeaders, { tags: { my_route: 'inventory' } }));

        const skip = Math.floor(Math.random() * 20) * 50;
        const ledRes = http.get(`${BASE_URL}/warehouse/ledger?skip=${skip}&limit=50`, Object.assign({}, adminHeaders, { tags: { my_route: 'ledger' } }));
        check(ledRes, { 'ledger 200': (r) => r.status === 200 });
    }

    sleep(randomIntBetween(1, 3));
}

export function loginStormFn(data) {
    const driverId = randomIntBetween(1, NUM_DRIVERS);
    const res = http.post(`${BASE_URL}/driver/login`,
        JSON.stringify({ username: `driver_test_${driverId}`, password: 'Driver1234!' }),
        { headers: { 'Content-Type': 'application/json' }, tags: { my_route: 'login_driver' } });

    // +++ الكي الجراحي: تقليل وقت الانتظار جداً لإجبار السيرفر على تجاوز 200 طلب/دقيقة +++
    if (res.status === 429) {
        shieldHits.add(1); // +++ تسجيل تصدي الدرع فعلياً في العداد +++
    }
    sleep(0.1); 
}

export function handleSummary(data) {
    const stamp = new Date().toISOString();
    const m = data.metrics;
    
    const getRate = (metric) => metric && metric.values ? (metric.values.rate * 100).toFixed(2) + '%' : 'N/A';
    const getP95 = (metric) => metric && metric.values && metric.values['p(95)'] !== undefined ? metric.values['p(95)'].toFixed(0) + 'ms' : 'N/A';
    const getMax = (metric) => metric && metric.values && metric.values.max !== undefined ? metric.values.max.toFixed(0) + 'ms' : 'N/A';
    const getCount = (metric) => metric && metric.values ? metric.values.count : 'N/A';
    const getReqRate = (metric) => metric && metric.values && metric.values.rate ? metric.values.rate.toFixed(2) : 'N/A';

    const lines = [
        '╔══════════════════════════════════════════════════════╗',
        '║   WANASAH — Nuclear Stress Test Report               ║',
        '║   Generated: ' + stamp,
        '╚══════════════════════════════════════════════════════╝',
        '',
        '  إجمالي الطلبات      : ' + getCount(m.http_reqs),
        '  معدل الطلبات/ثانية  : ' + getReqRate(m.http_reqs),
        '  نسبة الفشل          : ' + getRate(m.http_req_failed),
        '  P95 زمن الاستجابة   : ' + getP95(m.http_req_duration),
        '  أبطأ طلب            : ' + getMax(m.http_req_duration),
        '',
        '  التفاصيل الكاملة في: nuclear_summary.json',
        '',
    ];

    // +++ الكي الجراحي: استخراج المقاييس فقط (metrics) وتجاهل (setup_data) لمنع تسريب التوكنات +++
    const safeData = {
        generated_at: stamp,
        target_vus: TARGET_VUS,
        metrics: m
    };

    return {
        stdout: textSummary(data, { indent: ' ', enableColors: true }) + '\n' + lines.join('\n'),
        'nuclear_summary.json': JSON.stringify(safeData, null, 2),
    };
}