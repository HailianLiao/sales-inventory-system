
// ========== 通用工具函数 ==========

function showLoading(text) {
    document.getElementById("loadingText").textContent = text || "加载中...";
    document.getElementById("loadingOverlay").style.display = "flex";
}
function hideLoading() {
    document.getElementById("loadingOverlay").style.display = "none";
}

// AJAX POST 封装
function apiPost(url, data, callback) {
    showLoading();
    $.ajax({
        url: url, type: "POST", contentType: "application/json",
        data: JSON.stringify(data),
        success: function(res) { hideLoading(); callback(null, res); },
        error: function(xhr) { hideLoading(); callback(xhr.responseText || "请求失败"); }
    });
}

// 渲染 DataTable
function renderTable(selector, columns, data, options) {
    options = options || {};
    if ($.fn.dataTable.isDataTable(selector)) {
        $(selector).DataTable().destroy();
    }
    $(selector).DataTable({
        data: data, columns: columns,
        pageLength: options.pageLength || 25,
        order: options.order || [],
        language: { search: "搜索:", lengthMenu: "显示 _MENU_ 条", info: "共 _TOTAL_ 条", paginate: { first: "首页", last: "末页", next: "下一页", previous: "上一页" }, emptyTable: "暂无数据" },
        dom: options.dom || '<"row"<"col-sm-6"l><"col-sm-6"f>>rtip',
        scrollX: true, autoWidth: true
    });
}

// 渲染 ECharts 图表
function renderChart(domId, option) {
    var chart = echarts.init(document.getElementById(domId));
    chart.setOption(option);
    window.addEventListener("resize", function() { chart.resize(); });
    return chart;
}

// 下载 CSV
function downloadCSV(url) {
    window.open(url, "_blank");
}

// 格式化数字
function fmtNum(n) {
    if (n === null || n === undefined) return "-";
    return Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

// ========== 侧边栏折叠 ==========
document.addEventListener("DOMContentLoaded", function() {
    var toggle = document.getElementById("sidebarToggle");
    if (toggle) {
        toggle.addEventListener("click", function() {
            document.getElementById("sidebar").classList.toggle("collapsed");
            document.getElementById("main-content").classList.toggle("expanded");
            // 触发图表 resize
            window.dispatchEvent(new Event("resize"));
        });
    }
});
