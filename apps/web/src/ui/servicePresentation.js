export function serviceConnectionLabel(providerMode) {
    return providerMode === 'disabled' ? '学习服务未连接' : '学习服务已连接';
}

export function developmentServiceNotice(providerMode) {
    return providerMode === 'disabled'
        ? '学习服务未连接，不产生外部服务费用'
        : providerMode === 'test'
            ? '已连接本地测试服务，不产生外部服务费用'
            : '已连接正式学习服务，调用受后台预算授权控制';
}
