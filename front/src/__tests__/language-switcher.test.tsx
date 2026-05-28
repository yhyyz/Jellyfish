/**
 * P5 W28：4 语言切换器 + i18n 完整性测试。
 *
 * 覆盖范围：
 *   1. i18n 实例 supportedLngs 包含 zh-CN / en-US / ja-JP / ko-KR 4 项；
 *   2. resources 4 个 locale 节点都已注册 5 个命名空间；
 *   3. ja-JP / ko-KR 关键 key 翻译查找命中（layout.title / common.cancel /
 *      commerce.voicePackPicker.errorRetry 等）；
 *   4. useAppStore.setLanguage 接受 4 locale 字符串并更新 store；
 *   5. 渲染包含 antd Select 的语言切换器：4 项选项可见，
 *      选择 ja-JP / ko-KR 触发 setLanguage + i18n.changeLanguage 联动。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { Select } from 'antd'

import i18n from '../i18n'
import { useAppStore } from '../store/useAppStore'

describe('P5 W28: i18n 4-locale completeness', () => {
  it('supportedLngs 包含 4 个 BCP47 locale', () => {
    const supported = (i18n.options.supportedLngs ?? []) as readonly string[]
    expect(supported).toEqual(
      expect.arrayContaining(['zh-CN', 'en-US', 'ja-JP', 'ko-KR']),
    )
  })

  it('resources 包含 4 个 locale 各 5 个命名空间', () => {
    const resources = i18n.options.resources ?? {}
    for (const locale of ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']) {
      const ns = resources[locale]
      expect(ns, `locale ${locale} missing in resources`).toBeTruthy()
      for (const key of ['common', 'layout', 'settings', 'notFound', 'commerce']) {
        expect(
          (ns as Record<string, unknown>)[key],
          `${locale}.${key} missing`,
        ).toBeDefined()
      }
    }
  })

  it('ja-JP 翻译可查找（layout.title / common.cancel / voicePackPicker.errorRetry）', () => {
    expect(i18n.getResource('ja-JP', 'layout', 'title')).toBe('Jellyfish')
    expect(i18n.getResource('ja-JP', 'common', 'cancel')).toBe('キャンセル')
    expect(
      i18n.getResource('ja-JP', 'commerce', 'voicePackPicker.errorRetry'),
    ).toBe('読み込みに失敗しました。クリックして再試行')
    expect(i18n.getResource('ja-JP', 'layout', 'lang.ja')).toBe('日本語')
  })

  it('ko-KR 翻译可查找（layout.title / common.cancel / voicePackPicker.errorRetry）', () => {
    expect(i18n.getResource('ko-KR', 'layout', 'title')).toBe('Jellyfish')
    expect(i18n.getResource('ko-KR', 'common', 'cancel')).toBe('취소')
    expect(
      i18n.getResource('ko-KR', 'commerce', 'voicePackPicker.errorRetry'),
    ).toBe('로드에 실패했습니다. 클릭하여 다시 시도')
    expect(i18n.getResource('ko-KR', 'layout', 'lang.ko')).toBe('한국어')
  })

  it('zh-CN / en-US 的 layout.lang 子节点都含 ja / ko 两项', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      expect(i18n.getResource(locale, 'layout', 'lang.ja')).toBe('日本語')
      expect(i18n.getResource(locale, 'layout', 'lang.ko')).toBe('한국어')
    }
  })
})

describe('P5 W28: useAppStore.setLanguage 接受 4 locale', () => {
  beforeEach(() => {
    useAppStore.setState({ language: 'zh-CN' })
  })

  it('setLanguage 接受 ja-JP / ko-KR / en-US / zh-CN', () => {
    useAppStore.getState().setLanguage('ja-JP')
    expect(useAppStore.getState().language).toBe('ja-JP')

    useAppStore.getState().setLanguage('ko-KR')
    expect(useAppStore.getState().language).toBe('ko-KR')

    useAppStore.getState().setLanguage('en-US')
    expect(useAppStore.getState().language).toBe('en-US')

    useAppStore.getState().setLanguage('zh-CN')
    expect(useAppStore.getState().language).toBe('zh-CN')
  })
})

/**
 * 极简 LanguageSwitcher 组件，复刻 MainLayout 中 Select 的核心交互逻辑：
 *   onChange -> setLanguage(value) + i18n.changeLanguage(value)。
 * 不引入 MainLayout 全部依赖（react-router、TaskRuntimeProvider 等），
 * 只验证 antd Select 4 项选项 + 切换语言时双调动作。
 */
function MiniLanguageSwitcher() {
  const language = useAppStore((s) => s.language)
  const setLanguage = useAppStore((s) => s.setLanguage)
  return (
    <Select
      aria-label="language-switcher"
      value={language}
      onChange={(value) => {
        setLanguage(value)
        void i18n.changeLanguage(value)
      }}
      options={[
        { label: '简体中文', value: 'zh-CN' },
        { label: 'English', value: 'en-US' },
        { label: '日本語', value: 'ja-JP' },
        { label: '한국어', value: 'ko-KR' },
      ]}
    />
  )
}

describe('P5 W28: LanguageSwitcher UI 4 项 + 切换联动', () => {
  // i18n.changeLanguage 的精确签名 (lng?, callback?) => Promise<TFunction>
  // 与 vitest MockInstance<unknown> 之间存在 TS 兼容差，与 VoicePackLibrary
  // 测试同模式：用 any 别名故意放宽。
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let changeLangSpy: any

  beforeEach(() => {
    useAppStore.setState({ language: 'zh-CN' })
    changeLangSpy = vi
      .spyOn(i18n, 'changeLanguage')
      .mockImplementation(() => Promise.resolve(((k: string) => k) as never))
  })

  afterEach(() => {
    changeLangSpy.mockRestore()
  })

  it('打开下拉时显示 4 项语言选项（中 / 英 / 日 / 韩）', async () => {
    render(<MiniLanguageSwitcher />)
    const combo = screen.getByRole('combobox', { name: /language-switcher/i })
    fireEvent.mouseDown(combo)

    await waitFor(() => {
      const opts = screen
        .getAllByText(/简体中文|English|日本語|한국어/)
        .filter((el) => el.className.includes('ant-select-item-option-content'))
      expect(opts.length).toBe(4)
    })
  })

  it('点击「日本語」触发 setLanguage("ja-JP") + i18n.changeLanguage("ja-JP")', async () => {
    render(<MiniLanguageSwitcher />)
    const combo = screen.getByRole('combobox', { name: /language-switcher/i })
    fireEvent.mouseDown(combo)

    const options = await screen.findAllByText('日本語')
    const clickable = options.find((el) =>
      el.className.includes('ant-select-item-option-content'),
    )
    expect(clickable).toBeTruthy()
    fireEvent.click(clickable!)

    await waitFor(() => {
      expect(useAppStore.getState().language).toBe('ja-JP')
    })
    expect(changeLangSpy).toHaveBeenCalledWith('ja-JP')
  })

  it('点击「한국어」触发 setLanguage("ko-KR") + i18n.changeLanguage("ko-KR")', async () => {
    render(<MiniLanguageSwitcher />)
    const combo = screen.getByRole('combobox', { name: /language-switcher/i })
    fireEvent.mouseDown(combo)

    const options = await screen.findAllByText('한국어')
    const clickable = options.find((el) =>
      el.className.includes('ant-select-item-option-content'),
    )
    expect(clickable).toBeTruthy()
    fireEvent.click(clickable!)

    await waitFor(() => {
      expect(useAppStore.getState().language).toBe('ko-KR')
    })
    expect(changeLangSpy).toHaveBeenCalledWith('ko-KR')
  })
})
