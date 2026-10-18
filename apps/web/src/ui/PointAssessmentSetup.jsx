import React, { useContext, useState } from 'react';
import { UiLocaleContext } from './UiLocale';
import { pointMarksBasisPoints, secondPurposes } from './assessmentPointPolicy.js';

const typeKeys = { MCQ_SINGLE: 'singleChoice', NUMERIC: 'calculation', SHORT_TEXT: 'shortText',
    EXPLANATION: 'explanation', CODE: 'code' };

/** Content-free configuration only: no question, answer or source text. */
export function PointAssessmentSetup({ setup, slots, course, node, busy, formsFor,
    onType, onForm, onPurpose, onAdd, onRemove, onStart, onPrepare, prepareUncertain,
    onChooseLanguage = /** @type {((language: string) => void) | null} */ (null),
    languageLocked = false }) {
    const { t } = useContext(UiLocaleContext);
    const [purposes, setPurposes] = useState({});
    let marks = [], valid = false;
    try { marks = pointMarksBasisPoints(setup, slots); valid = true; } catch { /* Fail closed. */ }
    const count = setup.status === 'READY' && setup.points?.length ? setup.points.length : null;
    const heading = <div className="assessment-setup-intro">
        <h2>{t('assessment.setupTitle')}</h2><p>{course.code} · {node.title}</p>
        {onChooseLanguage && <AssessmentContentLanguageChoice onChoose={onChooseLanguage}
            value={setup.content_language} disabled={busy || prepareUncertain || languageLocked}/>}
        <p className="helper-note"><span>{count === null ? t('assessment.pointCountPending')
            : t('assessment.pointCount', { count })}</span>
            {' · '}{t('assessment.onePerPoint')}{' · '}{t('assessment.maxTwo')}</p>
        {count === null && Number.isInteger(setup.candidate_target_count) && setup.candidate_target_count >= 0 &&
            <p className="helper-note">{t('assessment.candidateTargetCount', { count: setup.candidate_target_count })}</p>}
    </div>;
    if (setup.status !== 'READY' || !setup.points?.length) return <div className="assessment-setup assessment-point-setup">
        {heading}<p role="status">{t(setup.next_action==='reconcile_original_request'
            ? 'assessment.pointRequestUncertain' : 'assessment.pointsNotReady')}</p>
        <button type="button" className="btn primary" disabled={busy || prepareUncertain || setup.next_action==='reconcile_original_request'} onClick={onPrepare}>
            {t(busy ? 'assessment.preparingPoints' : 'assessment.preparePoints')}</button>
    </div>;
    return <div className="assessment-setup assessment-point-setup">{heading}<div className="assessment-slot-list">
        {slots.map((slot, index) => {
            const ordinal = t('assessment.questionOrdinal', { number: index + 1 });
            const point = setup.points.find(p => p.point_id === slot.primary_point_id);
            const isSecond = slots.slice(0, index).some(s => s.primary_point_id === slot.primary_point_id);
            return <div className="assessment-slot-row" key={slot.slot_id}>
                <strong>{ordinal}<small> · {t('assessment.point')} {setup.points.indexOf(point) + 1}</small></strong>
                <label><span>{t('assessment.form')}</span>
                    <select aria-label={`${ordinal} · ${t('assessment.form')}`} value={slot.question_type}
                        disabled={busy} onChange={e => onType(index, e.target.value)}>
                        {(point?.allowed_forms || []).map(type => <option key={type} value={type}>
                            {t(`assessment.${typeKeys[type]}`)}</option>)}
                    </select></label>
                <label><span>{t('assessment.ability')}</span>
                    <select aria-label={`${ordinal} · ${t('assessment.ability')}`} value={slot.task_form}
                        disabled={busy} onChange={e => onForm(index, e.target.value)}>
                        {formsFor(slot.question_type, setup.task_forms || []).map(form => <option key={form.id} value={form.id}>
                            {t(`assessment.taskForm.${form.id}`)}</option>)}
                    </select></label>
                {isSecond && <label className="assessment-second-purpose"><span>{t('assessment.secondPurpose')}</span>
                    <select aria-label={`${ordinal} · ${t('assessment.secondPurpose')}`} value={slot.variation_purpose || ''}
                        disabled={busy} onChange={e => onPurpose(index, e.target.value)}>
                        {Object.entries(secondPurposes).map(([value, label]) => <option key={value} value={value}>
                            {t(`assessment.${label}`)}</option>)}
                    </select></label>}
                <span className="assessment-slot-marks">{valid ? t('assessment.marks', { marks: (marks[index] / 100).toFixed(2) }) : '—'}</span>
                <button type="button" className="icon-btn" aria-label={t('assessment.deleteQuestion', { number: index + 1 })}
                    disabled={busy || !isSecond} onClick={() => onRemove(index)}>−</button>
            </div>;
        })}
    </div><div className="assessment-slot-list">{setup.points.map((point, index) => {
        const count = slots.filter(slot => slot.primary_point_id === point.point_id).length;
        if (count >= 2) return null;
        return <div className="assessment-slot-row" key={point.point_id}>
            <strong>{t('assessment.point')} {index + 1}</strong>
            <label><span>{t('assessment.secondPurpose')}</span>
                <select aria-label={t('assessment.addPurpose', { number: index + 1 })}
                    value={purposes[point.point_id] || ''} disabled={busy}
                    onChange={e => setPurposes({ ...purposes, [point.point_id]: e.target.value })}>
                    <option value="">{t('assessment.choosePurpose')}</option>
                    {Object.entries(secondPurposes).map(([value, label]) => <option key={value} value={value}>
                        {t(`assessment.${label}`)}</option>)}
                </select></label>
            <button type="button" className="btn" disabled={busy || !count || !purposes[point.point_id]}
                onClick={() => onAdd(point.point_id, purposes[point.point_id])}>
                {t('assessment.addSecond', { number: index + 1 })}</button>
        </div>;
    })}</div><div className="assessment-setup-actions">
        <span className="helper-note">{t('assessment.totalMarks', { marks: '100.00' })}</span>
        <button type="button" className="btn primary" disabled={busy || !valid} onClick={onStart}>
            {t(busy ? 'assessment.confirming' : 'assessment.confirmStart')}</button>
    </div></div>;
}
export function AssessmentContentLanguageChoice({ onChoose, value = '', disabled = false }) {
    const { t } = useContext(UiLocaleContext);
    return <div className="assessment-start"><label>{t('assessment.contentLanguage')}
        <select aria-label={t('assessment.contentLanguage')} value={value} disabled={disabled}
            onChange={event => { if (event.target.value) onChoose(event.target.value); }}>
            <option value="">{t('assessment.chooseContentLanguage')}</option>
            <option value="zh-CN">中文</option><option value="en">English</option>
        </select></label><p className="helper-note">{t('assessment.contentLanguageNotice')}</p></div>;
}

