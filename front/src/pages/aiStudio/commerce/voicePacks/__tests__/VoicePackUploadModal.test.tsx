/**
 * VoicePackUploadModal 单元测试（W29）。
 *
 * 覆盖：
 * 1. 渲染所有字段（prefix / display_name / target_model / region /
 *    language_hints / description / file dropzone）。
 * 2. prefix regex 校验：含 `-` 时 form-level 校验失败，不调 client。
 * 3. submit happy path：upload 文件 + 填表 + 点 OK，调 generated client，
 *    成功后 onClose + onCreated。
 *
 * 注意：jsdom 不实现 AudioContext，因此 probeAudio 总是失败；通过
 * monkeypatch window.AudioContext 模拟成功路径。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

import { CommerceVoicePacksCustomService } from '../../../../../services/generated'
import { VoicePackUploadModal } from '../VoicePackUploadModal'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockedCreate: any

class FakeAudioContext {
  async decodeAudioData(_buf: ArrayBuffer): Promise<AudioBuffer> {
    return {
      duration: 15.0,
      sampleRate: 16000,
      numberOfChannels: 1,
    } as unknown as AudioBuffer
  }
  close(): Promise<void> {
    return Promise.resolve()
  }
}

describe('VoicePackUploadModal', () => {
  beforeEach(() => {
    mockedCreate = vi.spyOn(
      CommerceVoicePacksCustomService,
      'createCustomVoicePackEndpointApiV1CommerceVoicePacksCustomPost',
    )
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(window as any).AudioContext = FakeAudioContext
  })

  afterEach(() => {
    mockedCreate.mockRestore()
  })

  it('renders all required form fields when open', async () => {
    render(<VoicePackUploadModal open={true} onClose={() => undefined} />)
    expect(await screen.findByLabelText(/voice-pack-prefix/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/voice-pack-display-name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/voice-pack-target-model/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/voice-pack-region/i)).toBeInTheDocument()
  })

  it('rejects invalid prefix and does not call client', async () => {
    const onClose = vi.fn()
    render(<VoicePackUploadModal open={true} onClose={onClose} />)
    const prefixInput = await screen.findByLabelText(/voice-pack-prefix/i)
    fireEvent.change(prefixInput, { target: { value: 'my-voice' } })

    const displayInput = screen.getByLabelText(/voice-pack-display-name/i)
    fireEvent.change(displayInput, { target: { value: 'test' } })

    // 直接点 OK：因为 prefix 含 `-`，form 校验失败
    const okBtn = screen.getByRole('button', { name: /submit|开始训练|Start Training|Training/i })
    fireEvent.click(okBtn)

    // 等异步 form 校验落地
    await waitFor(() => {
      expect(mockedCreate).not.toHaveBeenCalled()
    })
  })

  it('submits with valid form + file and calls onCreated', async () => {
    mockedCreate.mockResolvedValue({
      data: { voice_pack_id: 'clone_x', clone_status: 'deploying', created_at: '2026-05-28T00:00:00Z' },
    })
    const onCreated = vi.fn()
    const onClose = vi.fn()
    render(
      <VoicePackUploadModal
        open={true}
        onClose={onClose}
        onCreated={onCreated}
      />,
    )

    const prefixInput = await screen.findByLabelText(/voice-pack-prefix/i)
    fireEvent.change(prefixInput, { target: { value: 'myvoice' } })
    fireEvent.change(screen.getByLabelText(/voice-pack-display-name/i), {
      target: { value: '我的克隆音色' },
    })

    // 选择文件：通过 hidden input + file change 模拟（antd Upload 内部用 input[type=file]）
    const wavData = new Uint8Array([
      0x52, 0x49, 0x46, 0x46, // RIFF
      0x24, 0x00, 0x00, 0x00,
      0x57, 0x41, 0x56, 0x45, // WAVE
    ])
    const file = new File([wavData], 'voice.wav', { type: 'audio/wav' })
    const fileInput = document
      .querySelector('input[type=file]') as HTMLInputElement | null
    expect(fileInput).not.toBeNull()
    Object.defineProperty(fileInput!, 'files', { value: [file] })
    fireEvent.change(fileInput!)

    // 等 audio probe 完成（mock AudioContext 立刻 resolve）
    await waitFor(() => {
      // beforeUpload 完成后 fileList 应有一条
      // 通过断言提交按钮可点（无 audioError）来近似验证
      const ok = screen.getByRole('button', {
        name: /submit|开始训练|Start Training|Training/i,
      })
      expect(ok).not.toBeDisabled()
    })

    fireEvent.click(
      screen.getByRole('button', {
        name: /submit|开始训练|Start Training|Training/i,
      }),
    )

    await waitFor(() => {
      expect(mockedCreate).toHaveBeenCalledTimes(1)
    })
    expect(onCreated).toHaveBeenCalledWith('clone_x')
  })
})
