import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import zhLayout from './locales/zh-CN/layout.json'
import zhCommon from './locales/zh-CN/common.json'
import zhSettings from './locales/zh-CN/settings.json'
import zhNotFound from './locales/zh-CN/notFound.json'
// W20 Wave C：注册剧情带货模块（音色/字幕/AV 预览等）的 i18n 命名空间
import zhCommerce from './locales/zh-CN/commerce.json'
import enLayout from './locales/en-US/layout.json'
import enCommon from './locales/en-US/common.json'
import enSettings from './locales/en-US/settings.json'
import enNotFound from './locales/en-US/notFound.json'
import enCommerce from './locales/en-US/commerce.json'
// P5 W28：完整化 ja-JP / ko-KR 整树（5 命名空间 mirror zh-CN）
import jaLayout from './locales/ja-JP/layout.json'
import jaCommon from './locales/ja-JP/common.json'
import jaSettings from './locales/ja-JP/settings.json'
import jaNotFound from './locales/ja-JP/notFound.json'
import jaCommerce from './locales/ja-JP/commerce.json'
import koLayout from './locales/ko-KR/layout.json'
import koCommon from './locales/ko-KR/common.json'
import koSettings from './locales/ko-KR/settings.json'
import koNotFound from './locales/ko-KR/notFound.json'
import koCommerce from './locales/ko-KR/commerce.json'

export type SupportedLanguage = 'zh-CN' | 'en-US' | 'ja-JP' | 'ko-KR'

const resources = {
  'zh-CN': {
    common: zhCommon,
    layout: zhLayout,
    settings: zhSettings,
    notFound: zhNotFound,
    commerce: zhCommerce,
  },
  'en-US': {
    common: enCommon,
    layout: enLayout,
    settings: enSettings,
    notFound: enNotFound,
    commerce: enCommerce,
  },
  'ja-JP': {
    common: jaCommon,
    layout: jaLayout,
    settings: jaSettings,
    notFound: jaNotFound,
    commerce: jaCommerce,
  },
  'ko-KR': {
    common: koCommon,
    layout: koLayout,
    settings: koSettings,
    notFound: koNotFound,
    commerce: koCommerce,
  },
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: 'zh-CN',
    supportedLngs: ['zh-CN', 'en-US', 'ja-JP', 'ko-KR'],
    ns: ['common', 'layout', 'settings', 'notFound', 'commerce'],
    defaultNS: 'layout',
    interpolation: {
      escapeValue: false,
    },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      lookupLocalStorage: 'jellyfish_language',
    },
  })

export default i18n
