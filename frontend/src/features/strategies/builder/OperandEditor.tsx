import { Link2, Sigma, Unlink, X } from 'lucide-react'
import { useId } from 'react'
import { useTranslation } from '@/i18n'
import { cn } from '@/shared/lib/utils'
import { Button } from '@/shared/ui/button'
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/shared/ui/select'
import {
  ARITHMETIC_OPERATORS,
  INDICATOR_KINDS,
  LIMITS,
  MARKET_FIELDS,
  VOLUME_KINDS,
  indicatorSpec,
  readParam,
} from '../model/catalog'
import { SYMBOLS, describeIndicator } from '../model/describe'
import {
  defaultIndicator,
  indicatorUsage,
  indicatorsOfKind,
  newIndicatorId,
  type IndicatorTable,
  type StrategyEdit,
} from '../model/edit'
import type {
  ArithmeticOperator,
  ExpressionPath,
  IdFactory,
  IndicatorId,
  IndicatorKind,
  IndicatorOutput,
  NodeId,
  NumericExpression,
  Strategy,
} from '../model/types'
import { exprPath } from '../model/validate'
import { useFormulaText } from '../use-formula-text'
import { DayField, Field, FieldError, NumberField, type IssueLookup } from './fields'

export interface OperandContext {
  strategy: Strategy
  conditionId: NodeId
  edit: (change: StrategyEdit) => void
  issue: IssueLookup
  ids: IdFactory
}

interface OperandEditorProps {
  context: OperandContext
  path: ExpressionPath
  expression: NumericExpression
  depth?: number
  volumeUnit?: boolean
}

type Source = 'market' | 'latest_price' | 'indicator' | 'constant'

export function OperandEditor({ context, path, expression, depth = 0, volumeUnit = false }: OperandEditorProps) {
  const { t } = useTranslation('builder')
  const { strategy, conditionId, edit } = context
  const set = (next: NumericExpression, indicators: IndicatorTable = {}) =>
    edit({ type: 'setExpression', conditionId, path, expression: next, indicators })

  if (expression.type === 'arithmetic') {
    return <ArithmeticEditor context={context} path={path} expression={expression} depth={depth} volumeUnit={volumeUnit} />
  }

  const changeSource = (source: Source) => {
    if (source === expression.type) return
    if (source === 'market') return set({ type: 'market', field: 'close', barsAgo: 0 })
    if (source === 'latest_price') return set({ type: 'latest_price' })
    if (source === 'constant') return set({ type: 'constant', value: 0 })
    const existing = indicatorsOfKind(strategy, 'sma')[0]
    if (existing) return set({ type: 'indicator', indicatorId: existing, output: 'value', barsAgo: 0 })
    const id = newIndicatorId(context.ids)
    set({ type: 'indicator', indicatorId: id, output: 'value', barsAgo: 0 }, { [id]: defaultIndicator('sma') } as IndicatorTable)
  }

  const canWrap = depth < LIMITS.maxArithmeticDepthInEditor
  const wrap = () =>
    set({ type: 'arithmetic', operator: 'multiply', left: expression, right: { type: 'constant', value: 1 } })

  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-3">
      <SourcePicker value={expression.type} onChange={changeSource} />
      {expression.type === 'market' && (
        <MarketFields context={context} path={path} expression={expression} onChange={set} />
      )}
      {expression.type === 'indicator' && (
        <IndicatorFields context={context} path={path} expression={expression} onChange={set} />
      )}
      {expression.type === 'latest_price' && (
        <p className="col-span-full text-[0.6875rem] leading-relaxed text-muted-foreground sm:col-span-1">{t('operand.latestPriceHint')}</p>
      )}
      {expression.type === 'constant' && (
        <NumberField
          label={t('operand.value')}
          value={expression.value}
          onChange={(value) => set({ type: 'constant', value })}
          issue={context.issue(exprPath(conditionId, path, 'value'))}
          suffix={volumeUnit ? t('formula:unit.shares') : undefined}
          step={0.1}
        />
      )}
      {canWrap && (
        <div className="col-span-full">
          <Button type="button" variant="ghost" size="sm" onClick={wrap} className="px-2 text-xs text-muted-foreground md:h-7">
            <Sigma aria-hidden className="size-3.5" />
            {t('operand.addMath')}
          </Button>
        </div>
      )}
    </div>
  )
}

function SourcePicker({ value, onChange }: { value: Source; onChange: (source: Source) => void }) {
  const { t } = useTranslation('builder')
  const id = useId()
  return (
    <Field label={t('operand.source')} htmlFor={id}>
      <Select value={value} onValueChange={(next) => onChange(next as Source)}>
        <SelectTrigger id={id} className="w-full md:h-9">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="market">{t('operand.sourceMarket')}</SelectItem>
          <SelectItem value="latest_price">{t('operand.sourceLatestPrice')}</SelectItem>
          <SelectItem value="indicator">{t('operand.sourceIndicator')}</SelectItem>
          <SelectItem value="constant">{t('operand.sourceConstant')}</SelectItem>
        </SelectContent>
      </Select>
    </Field>
  )
}

function MarketFields({
  context,
  path,
  expression,
  onChange,
}: {
  context: OperandContext
  path: ExpressionPath
  expression: Extract<NumericExpression, { type: 'market' }>
  onChange: (next: NumericExpression) => void
}) {
  const { t } = useTranslation('builder')
  const id = useId()
  return (
    <>
      <Field label={t('operand.field')} htmlFor={id}>
        <Select value={expression.field} onValueChange={(field) => onChange({ ...expression, field: field as typeof expression.field })}>
          <SelectTrigger id={id} className="w-full md:h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {MARKET_FIELDS.map((field) => (
              <SelectItem key={field} value={field}>
                {t(`formula:fieldLabel.${field}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <DayField
        value={expression.barsAgo}
        onChange={(barsAgo) => onChange({ ...expression, barsAgo })}
        issue={context.issue(exprPath(context.conditionId, path, 'barsAgo'))}
        hint={expression.field === 'volume' ? t('operand.volumeUnitHint') : undefined}
      />
    </>
  )
}

function IndicatorFields({
  context,
  path,
  expression,
  onChange,
}: {
  context: OperandContext
  path: ExpressionPath
  expression: Extract<NumericExpression, { type: 'indicator' }>
  onChange: (next: NumericExpression, indicators?: IndicatorTable) => void
}) {
  const { t } = useTranslation('builder')
  const text = useFormulaText()
  const kindId = useId()
  const settingId = useId()
  const outputId = useId()
  const { strategy, conditionId, edit, issue } = context
  const config = strategy.indicators[expression.indicatorId]
  if (!config) return <FieldError id={kindId} issue={issue(exprPath(conditionId, path))} />
  const spec = indicatorSpec(config.kind)
  const siblings = indicatorsOfKind(strategy, config.kind)
  const usage = indicatorUsage(strategy, expression.indicatorId)

  const changeKind = (kind: IndicatorKind) => {
    const output = indicatorSpec(kind).outputs[0]!
    const existing = indicatorsOfKind(strategy, kind)[0]
    if (existing) return onChange({ ...expression, indicatorId: existing, output })
    const id = newIndicatorId(context.ids)
    onChange({ ...expression, indicatorId: id, output }, { [id]: defaultIndicator(kind) } as IndicatorTable)
  }

  const changeSetting = (value: string) => {
    if (value !== '__new') return onChange({ ...expression, indicatorId: value as IndicatorId })
    const id = newIndicatorId(context.ids)
    onChange({ ...expression, indicatorId: id }, { [id]: defaultIndicator(config.kind) } as IndicatorTable)
  }

  const averageHint =
    config.kind === 'volume_sma'
      ? t(expression.barsAgo === 0 ? 'operand.averageIncludesToday' : 'operand.averageExcludesToday')
      : undefined

  return (
    <>
        <Field label={t('operand.indicator')} htmlFor={kindId}>
          <Select value={config.kind} onValueChange={(kind) => changeKind(kind as IndicatorKind)}>
            <SelectTrigger id={kindId} className="w-full md:h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>{t('operand.indicatorPrice')}</SelectLabel>
                {INDICATOR_KINDS.filter((kind) => !VOLUME_KINDS.includes(kind)).map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {t(`formula:indicatorKind.${kind}`)}
                  </SelectItem>
                ))}
              </SelectGroup>
              <SelectGroup>
                <SelectLabel>{t('operand.indicatorVolume')}</SelectLabel>
                {VOLUME_KINDS.map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {t(`formula:indicatorKind.${kind}`)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Field label={t('operand.setting')} htmlFor={settingId}>
          <Select value={expression.indicatorId} onValueChange={changeSetting}>
            <SelectTrigger id={settingId} className="w-full md:h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {siblings.map((id) => {
                const sibling = strategy.indicators[id]!
                return (
                  <SelectItem key={id} value={id}>
                    {describeIndicator(sibling, text)}
                    <span className="ml-1 text-xs text-muted-foreground">{t('operand.usedBy', { count: indicatorUsage(strategy, id) })}</span>
                  </SelectItem>
                )
              })}
              <SelectItem value="__new">{t('operand.newSetting')}</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        {spec.outputs.length > 1 && (
          <Field label={t('operand.output')} htmlFor={outputId}>
            <Select value={expression.output} onValueChange={(output) => onChange({ ...expression, output: output as IndicatorOutput })}>
              <SelectTrigger id={outputId} className="w-full md:h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {spec.outputs.map((output) => (
                  <SelectItem key={output} value={output}>
                    {t(`formula:output.${output}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        <DayField
          value={expression.barsAgo}
          onChange={(barsAgo) => onChange({ ...expression, barsAgo })}
          issue={issue(exprPath(conditionId, path, 'barsAgo'))}
          hint={averageHint}
        />

      <div className={cn('col-span-full rounded-lg border bg-background/60 p-3', usage > 1 && 'border-gold/35')}>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-3">
          {spec.params.map((param) => (
            <NumberField
              key={param.key}
              label={t(`formula:param.${param.key}`)}
              value={readParam(config, param.key)}
              step={param.step}
              min={param.min}
              max={param.max}
              onChange={(value) => edit({ type: 'setIndicatorParam', indicatorId: expression.indicatorId, key: param.key, value })}
              issue={issue(`indicator:${expression.indicatorId}:${param.key}`)}
              suffix={param.key === 'period' ? t('operand.daysSuffix') : undefined}
            />
          ))}
        </div>
        {usage > 1 ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-1.5 text-gold">
              <Link2 aria-hidden className="size-3.5" />
              {t('operand.sharedSetting', { count: usage })}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="text-xs md:h-7"
              onClick={() => edit({ type: 'detachIndicator', conditionId, path, newIndicatorId: newIndicatorId(context.ids) })}
            >
              <Unlink aria-hidden className="size-3.5" />
              {t('operand.detach')}
            </Button>
          </div>
        ) : (
          <p className="mt-2 text-[0.6875rem] text-muted-foreground">{t('operand.paramHint')}</p>
        )}
      </div>

    </>
  )
}

function ArithmeticEditor({
  context,
  path,
  expression,
  depth,
  volumeUnit,
}: {
  context: OperandContext
  path: ExpressionPath
  expression: Extract<NumericExpression, { type: 'arithmetic' }>
  depth: number
  volumeUnit: boolean
}) {
  const { t } = useTranslation('builder')
  const id = useId()
  const { conditionId, edit, issue } = context
  const unwrap = () => edit({ type: 'setExpression', conditionId, path, expression: expression.left, indicators: {} })
  const setOperator = (operator: ArithmeticOperator) =>
    edit({ type: 'setExpression', conditionId, path, expression: { ...expression, operator }, indicators: {} })
  const rightIsVolume = volumeUnit && (expression.operator === 'add' || expression.operator === 'subtract')

  return (
    <div className="col-span-full space-y-3 rounded-xl border border-dashed border-primary/30 bg-accent/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-primary">
          <Sigma aria-hidden className="size-3.5" />
          {t('operand.math')}
        </span>
        <Button type="button" variant="ghost" size="sm" onClick={unwrap} className="px-2 text-xs text-muted-foreground md:h-7">
          <X aria-hidden className="size-3.5" />
          {t('operand.removeMath')}
        </Button>
      </div>
      <OperandEditor context={context} path={[...path, 'left']} expression={expression.left} depth={depth + 1} volumeUnit={volumeUnit} />
      <Field label={t('operand.operator')} htmlFor={id} className="max-w-56">
        <Select value={expression.operator} onValueChange={(value) => setOperator(value as ArithmeticOperator)}>
          <SelectTrigger id={id} className="w-full md:h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ARITHMETIC_OPERATORS.map((operator) => (
              <SelectItem key={operator} value={operator}>
                <span className="w-4 text-center font-mono">{SYMBOLS[operator]}</span>
                {t(`formula:arithmetic.${operator}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <OperandEditor context={context} path={[...path, 'right']} expression={expression.right} depth={depth + 1} volumeUnit={rightIsVolume} />
      <FieldError id={`${id}-error`} issue={issue(exprPath(conditionId, path))} />
    </div>
  )
}
