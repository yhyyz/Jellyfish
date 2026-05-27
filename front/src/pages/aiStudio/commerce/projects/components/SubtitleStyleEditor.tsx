/**
 * 自定义字幕样式编辑器（W20-T3）。
 *
 * 作为 `SubtitleStylePicker` 的「自定义」tab 子组件：把用户在 web 习惯
 * 的 `#RRGGBB` hex 输入收上来，提交时通过 `colorCodec.toAss` 校验
 * 颜色合法性。任何字段验证失败都会触发**行内错误**且 **不**调
 * `onChange`，避免脏数据流到上游字幕渲染管线。
 *
 * 设计要点：
 * - 所有输入受控；颜色用普通 `Input`（而非 antd `ColorPicker`），方便
 *   验证「输入非法 hex」流程，与 `colorCodec` 的合法性约束语义对齐。
 * - 提交载荷使用 web hex（`#RRGGBB`），而非 ASS 字面量；交由调用方
 *   在写库 / 渲染前再做 `toAss` 转换。
 * - 验证错误本地化字符串与 commerce.json 中
 *   `subtitleStylePicker.invalidHex` 同义；当前组件直接使用中文硬编
 *   码（与 sibling 组件 `HookPatternSelector` 风格一致），i18n 化留
 *   待后续整体抽取。
 */
import React, { useState } from 'react'
import { Button, Form, Input, InputNumber, Radio, Space } from 'antd'
import { toAss } from './_subtitle/colorCodec'

/**
 * 自定义字幕样式提交载荷。
 *
 * 仅承载用户在编辑器里**实际能调**的可读字段，其它（如 ASS PlayRes /
 * 字体回退链）由系统模板兜底；调用方拿到 override 后自行决定如何
 * merge 进最终样式。
 */
export interface SubtitleStyleOverride {
  /** 字号（脚本像素，按 PlayResY=1920 计） */
  font_size: number
  /** 主填充色 web hex `#RRGGBB`（**未做** ASS 字节序转换） */
  primary_colour: string
  /** 描边色 web hex `#RRGGBB` */
  outline_colour: string
  /** 描边宽度（像素） */
  outline: number
  /** 阴影偏移（像素） */
  shadow: number
  /** ASS Alignment numpad（1-9） */
  alignment: number
  /** 垂直边距（像素） */
  margin_v: number
}

export interface SubtitleStyleEditorProps {
  /** 提交且校验通过后的回调，参数为编辑器收集到的 override 载荷 */
  onSubmit: (override: SubtitleStyleOverride) => void
  /** 编辑器初始值，未传则使用合理 defaults */
  initialValue?: Partial<SubtitleStyleOverride>
}

/**
 * 编辑器默认值。
 *
 * 跟 W18 `douyin_default` 大致对齐，但不引用具体 system style，避免循
 * 环耦合：picker 选择 system 模板时不会进编辑器，编辑器有自己的
 * 起手值即可。
 */
const DEFAULT_OVERRIDE: SubtitleStyleOverride = {
  font_size: 64,
  primary_colour: '#FFFFFF',
  outline_colour: '#000000',
  outline: 2,
  shadow: 1,
  alignment: 2,
  margin_v: 200,
}

/**
 * 自定义字幕样式编辑器组件。
 *
 * 受控 state 管理每个字段；提交按钮点击后：
 * 1. 通过 `toAss` 校验主色 / 描边色合法性，捕获异常 → 设错误并
 *    **不**调 `onSubmit`。
 * 2. 校验通过则把当前 state 浅拷贝传给 `onSubmit`。
 *
 * 注意 alignment 用 9 宫格 numpad（1-9）数字按钮，与 ASS 规范一致；
 * 1=底左 / 2=底中 / 3=底右 / 4=中左 / 5=中中 / 6=中右 / 7=顶左 /
 * 8=顶中 / 9=顶右。
 */
export const SubtitleStyleEditor: React.FC<SubtitleStyleEditorProps> = ({
  onSubmit,
  initialValue,
}) => {
  // 合并默认值与初始值，保证未传字段有合理 fallback
  const [override, setOverride] = useState<SubtitleStyleOverride>({
    ...DEFAULT_OVERRIDE,
    ...initialValue,
  })
  const [primaryColourError, setPrimaryColourError] = useState<string | null>(
    null,
  )
  const [outlineColourError, setOutlineColourError] = useState<string | null>(
    null,
  )

  /** 通用更新器，单字段写回保持其它字段不变。 */
  const update = <K extends keyof SubtitleStyleOverride>(
    key: K,
    value: SubtitleStyleOverride[K],
  ) => {
    setOverride((prev) => ({ ...prev, [key]: value }))
  }

  /**
   * 提交处理：
   * - 任一颜色非法都进入错误态（行内文案 + 跳过 `onSubmit`），
   *   两个颜色都尝试校验，方便用户一次看到全部问题。
   */
  const handleSubmit = () => {
    let hasError = false
    try {
      toAss(override.primary_colour)
      setPrimaryColourError(null)
    } catch {
      setPrimaryColourError('颜色格式不正确，应为 #RRGGBB')
      hasError = true
    }
    try {
      toAss(override.outline_colour)
      setOutlineColourError(null)
    } catch {
      setOutlineColourError('颜色格式不正确，应为 #RRGGBB')
      hasError = true
    }
    if (hasError) return
    onSubmit({ ...override })
  }

  return (
    <Form layout="vertical" onFinish={handleSubmit} component="div">
      <Form.Item label="字号">
        <div data-testid="subtitle-editor-font-size">
          <InputNumber
            min={12}
            max={200}
            value={override.font_size}
            onChange={(v) =>
              update('font_size', typeof v === 'number' ? v : 64)
            }
          />
        </div>
      </Form.Item>

      <Form.Item
        label="主色"
        validateStatus={primaryColourError ? 'error' : undefined}
        help={primaryColourError ?? undefined}
      >
        <Input
          data-testid="subtitle-editor-primary-colour"
          value={override.primary_colour}
          onChange={(e) => update('primary_colour', e.target.value)}
          placeholder="#RRGGBB"
        />
      </Form.Item>

      <Form.Item
        label="描边色"
        validateStatus={outlineColourError ? 'error' : undefined}
        help={outlineColourError ?? undefined}
      >
        <Input
          data-testid="subtitle-editor-outline-colour"
          value={override.outline_colour}
          onChange={(e) => update('outline_colour', e.target.value)}
          placeholder="#RRGGBB"
        />
      </Form.Item>

      <Form.Item label="描边">
        <InputNumber
          min={0}
          max={10}
          value={override.outline}
          onChange={(v) => update('outline', typeof v === 'number' ? v : 0)}
        />
      </Form.Item>

      <Form.Item label="阴影">
        <InputNumber
          min={0}
          max={10}
          value={override.shadow}
          onChange={(v) => update('shadow', typeof v === 'number' ? v : 0)}
        />
      </Form.Item>

      <Form.Item label="对齐位置">
        {/*
         * 9 宫格 numpad：直接用 Radio.Group 的 button 模式覆盖 1-9，
         * 视觉上虽是一行，但 ASS numpad 语义上是 3x3 的二维布局。
         */}
        <Radio.Group
          value={override.alignment}
          onChange={(e) => update('alignment', Number(e.target.value))}
          optionType="button"
          data-testid="subtitle-editor-alignment"
        >
          {[7, 8, 9, 4, 5, 6, 1, 2, 3].map((n) => (
            <Radio key={n} value={n}>
              {n}
            </Radio>
          ))}
        </Radio.Group>
      </Form.Item>

      <Form.Item label="底距">
        <InputNumber
          min={0}
          max={1000}
          value={override.margin_v}
          onChange={(v) => update('margin_v', typeof v === 'number' ? v : 0)}
        />
      </Form.Item>

      <Form.Item>
        <Space>
          <Button type="primary" onClick={handleSubmit}>
            应用
          </Button>
        </Space>
      </Form.Item>
    </Form>
  )
}

export default SubtitleStyleEditor
