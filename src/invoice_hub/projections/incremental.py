"""Build complete candidates from raw caches before publishing the one visible generation."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path

from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.storage import generations
from invoice_hub.storage.parse_cache import ParseCache, identity, scan_files, signature


def rebuild_generation(
    state,
    cost,
    summary_builder,
    progress,
    *,
    full=False,
    verify=False,
    outbound=None,
    export_to_source: bool = True,
):
    workspace, source = state.workspace_dir, state.watch_dir
    previous = generations.current(workspace, source)
    generations.recover_exports(workspace, source)
    root = identity(source)
    if previous and previous["root_identity"] != root:
        raise ValueError("来源根目录已被替换，旧完整结果已保留；请重新确认来源。")
    files = scan_files(source)
    stamps = {str(path): signature(path) for path in files}
    # External Excel edits during a long parse cannot be silently overwritten at publication.
    protected = [state.summary_xlsx, cost.summary_xlsx, cost.status_json, state.manual_overrides_file]
    before = {str(path): signature(path) if path.exists() else None for path in protected}
    with generations.candidate(workspace) as stage, ParseCache(workspace, verify=verify, rebuild=full) as cache:
        for name in generations.COST[1:]:
            path = source / name
            if path.exists():
                shutil.copyfile(path, stage / name)
        if cost.outbound_summary_json.exists():
            shutil.copyfile(cost.outbound_summary_json, stage / cost.outbound_summary_json.name)
        summary = summary_builder(source, stage, cache=cache, files=files, preview_workspace=workspace,
                                  progress=lambda done, total: progress.report_fraction("summary", "正在增量整理票头", done, total, 8, 52))
        staged_state = copy.copy(state)
        staged_state.summary_csv, staged_state.summary_xlsx = (stage / name for name in generations.SUMMARY)
        applied = staged_state.apply_manual_overrides_to_summary()
        staged_cost = CostProjectionService(source, stage, cost.target_id, reference_markup_rate=cost.reference_markup_rate,
                                            company_taxpayer=cost._company_taxpayer, company_outbound=cost._company_outbound, output_dir=stage)
        cost_result = staged_cost.rebuild(cache=cache, source_files=files, preview_workspace=workspace,
                                         progress=lambda done, total: progress.report_fraction("cost", "正在增量整理成本", done, total, 52, 92))
        if outbound is not None:
            cost_result["outbound"] = {key: value for key, value in staged_cost.refresh_outbound(outbound).items() if key != "items"}
        if cost_result.get("failed_count"):
            raise ValueError("部分文件解析失败，候选结果未发布；保留上次完整代际。")
        progress.report("finalizing", "正在复核源文件与手改版本", percent=92)
        processed = staged_state.rebuild_processed_from_summary()
        if identity(source) != root or scan_files(source) != files or any(signature(path) != stamps[str(path)] for path in files):
            raise ValueError("生成期间来源变化；候选结果未发布。")
        if any((signature(Path(path)) if Path(path).exists() else None) != stamp for path, stamp in before.items()):
            raise ValueError("生成期间工作簿或手改状态变化；已保留改动，请重新汇总。")
        progress.report("publishing", "正在发布完整结果", percent=95)
        published = generations.publish(
            workspace,
            source,
            stage,
            expected=previous.get("generation", ""),
            coverage=cache.stats(),
            export_to_source=export_to_source,
        )
        state.save_processed(processed)
        cost._save_tax_dependency()
        summary.update(summary_csv=str(state.summary_csv), summary_xlsx=str(state.summary_xlsx))
        cost_result.update(detail_csv=str(cost.detail_csv), summary_xlsx=str(cost.summary_xlsx), reference_status_json=str(cost.status_json))
        return summary, cost_result, applied, published
