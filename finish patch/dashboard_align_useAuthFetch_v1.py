from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'dashboard' / 'src' / 'hooks' / 'useAuthFetch.ts'


def fail(msg):
    raise SystemExit(f'PATCH_ABORTED: {msg}')


def rep(text, old, new, label):
    if new in text:
        print(f'ALREADY_PATCHED={label}')
        return text
    count = text.count(old)
    if count != 1:
        fail(f'{label}: expected 1 match, found {count}')
    print(f'PATCHED={label}')
    return text.replace(old, new, 1)


if not TARGET.exists():
    fail('dashboard/src/hooks/useAuthFetch.ts not found')

text = TARGET.read_text(encoding='utf-8')

text = rep(text,
"""const processQueue = (error: Error | null, token: string | null = null) => {
    failedQueue.forEach(prom => {
        if (error) prom.reject(error);
        else prom.resolve(token!);
    });
    failedQueue = [];
};
""",
"""const processQueue = (error: Error | null, token: string | null = null) => {
    failedQueue.forEach(prom => {
        if (error) prom.reject(error);
        else prom.resolve(token!);
    });
    failedQueue = [];
};

const makeHttpError = (message: string, status: number, data: any = null) => {
    const error: any = new Error(message);
    error.status = status;
    error.data = data;
    return error;
};
""", 'http_error_contract')

text = rep(text,
'''            forceLogout("انتهت الجلسة");
            throw new Error("انتهت الجلسة");
''',
'''            forceLogout("انتهت الجلسة");
            throw makeHttpError("انتهت الجلسة", 401);
''', 'missing_access_token_status')

text = rep(text,
'''                signal: opts.signal ?? timeoutController.signal,
''',
'''                signal: opts.signal
                    ? AbortSignal.any([opts.signal, timeoutController.signal])
                    : timeoutController.signal,
''', 'initial_timeout_with_external_abort')

text = rep(text,
'''                    forceLogout("جلسة منتهية تماماً");
                    throw new Error("جلسة منتهية");
''',
'''                    forceLogout("جلسة منتهية تماماً");
                    throw makeHttpError("جلسة منتهية", 401);
''', 'missing_refresh_token_status')

text = rep(text,
'''                        if (!refreshRes.ok) throw new Error("فشل تجديد الجلسة");
''',
'''                        if (!refreshRes.ok) {
                            throw makeHttpError("فشل تجديد الجلسة", refreshRes.status);
                        }
''', 'refresh_failure_status')

text = rep(text,
'''                        forceLogout("فشل التجديد");
                        throw new Error("تم تسجيل خروجك بسبب انتهاء الصلاحية الكلية");
''',
'''                        forceLogout("فشل التجديد");
                        throw makeHttpError(
                            "تم تسجيل خروجك بسبب انتهاء الصلاحية الكلية",
                            (refreshErr as any)?.status || 401
                        );
''', 'refresh_failure_contract')

text = rep(text,
'''                        signal: opts.signal ?? retryTimeoutController.signal,
''',
'''                        signal: opts.signal
                            ? AbortSignal.any([opts.signal, retryTimeoutController.signal])
                            : retryTimeoutController.signal,
''', 'retry_timeout_with_external_abort')

retry_anchor = '''                    res = await fetch(`${API}${cleanPath}`, {
                        ...opts,
                        signal: opts.signal
                            ? AbortSignal.any([opts.signal, retryTimeoutController.signal])
                            : retryTimeoutController.signal,
                        headers: {
                            "Content-Type": "application/json",
                            Authorization: `Bearer ${newToken}`,
                            ...(opts.headers ?? {})
                        },
                    });
'''
retry_new = retry_anchor + '''
                    if (res.status === 401) {
                        forceLogout("فشل التحقق بعد تجديد الجلسة");
                    }
'''
text = rep(text, retry_anchor, retry_new, 'post_refresh_401_fail_closed')

old_error = '''            if (!res.ok) {
                // إذا كان 403 (حساب موقوف إدارياً) نوجهه للخروج فوراً
                // نص المطابقة حرفي من dependencies.py:52 ("تم إيقاف حسابك") — لا نطرد عند 403 الصلاحيات العادية (مرفوض أمنياً: لا تملك صلاحية...)
                if (res.status === 403 && data?.detail?.includes("تم إيقاف حسابك")) {
                    forceLogout("تم إيقاف حسابك من قبل الإدارة");
                }
                const errorInstance: any = new Error(data?.detail || data?.message || `خطأ سيرفر (${res.status})`);
                throw errorInstance;
            }
'''
new_error = '''            if (!res.ok) {
                const serverMessage =
                    data?.message || data?.detail || `خطأ سيرفر (${res.status})`;

                if (
                    res.status === 403 &&
                    typeof serverMessage === "string" &&
                    serverMessage.includes("تم إيقاف حسابك")
                ) {
                    forceLogout("تم إيقاف حسابك من قبل الإدارة");
                }

                throw makeHttpError(serverMessage, res.status, data);
            }
'''
text = rep(text, old_error, new_error, 'backend_error_shape_alignment')

text = rep(text,
'''            if (err.name === 'AbortError') {
                throw new Error("انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.");
            }
''',
'''            if (err.name === 'AbortError') {
                if (opts.signal?.aborted) {
                    throw err;
                }
                throw makeHttpError(
                    "انتهت مهلة الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.",
                    408
                );
            }
''', 'abort_vs_timeout')

TARGET.write_text(text, encoding='utf-8')

checks = {
    'HTTP_STATUS': 'error.status = status;' in text,
    'MESSAGE_SHAPE': 'data?.message || data?.detail' in text,
    'POST_REFRESH_401': 'فشل التحقق بعد تجديد الجلسة' in text,
    'INITIAL_TIMEOUT': 'AbortSignal.any([opts.signal, timeoutController.signal])' in text,
    'RETRY_TIMEOUT': 'AbortSignal.any([opts.signal, retryTimeoutController.signal])' in text,
    'CALLER_ABORT': 'if (opts.signal?.aborted)' in text,
}
failed = [k for k,v in checks.items() if not v]
if failed:
    fail(f'static verification failed: {failed}')

print('USE_AUTH_FETCH_HTTP_CONTRACT=OK')
print('USE_AUTH_FETCH_BACKEND_ERROR_SHAPE=OK')
print('USE_AUTH_FETCH_REFRESH_FAIL_CLOSED=OK')
print('USE_AUTH_FETCH_ABORT_TIMEOUT=OK')
print('DASHBOARD_ALIGN_USE_AUTH_FETCH_V1=OK')
