export type Locale = 'de-DE' | 'en-US' | 'fr-FR' | 'ru-RU' | 'th-TH' | 'vi-VN' | 'zh-CN' | 'zh-TW';

export const messages: Record<Locale, Record<string, string>> = {
  'de-DE': {
    cancel: 'Abbrechen', collapse: 'Einklappen', confirm: 'Bestätigen', expand: 'Ausklappen',
    prompt: 'Hinweis', reset: 'Zurücksetzen', submit: 'Absenden', confirmTitle: 'Bitte bestätigen',
  },
  'en-US': {
    cancel: 'Cancel',
    collapse: 'Collapse',
    confirm: 'Confirm',
    expand: 'Expand',
    prompt: 'Prompt',
    reset: 'Reset',
    submit: 'Submit',
    confirmTitle: 'Please Confirm',
  },
  'fr-FR': {
    cancel: 'Annuler', collapse: 'Réduire', confirm: 'Confirmer', expand: 'Développer',
    prompt: 'Information', reset: 'Réinitialiser', submit: 'Envoyer', confirmTitle: 'Veuillez confirmer',
  },
  'ru-RU': {
    cancel: 'Отмена', collapse: 'Свернуть', confirm: 'Подтвердить', expand: 'Развернуть',
    prompt: 'Подсказка', reset: 'Сбросить', submit: 'Отправить', confirmTitle: 'Подтвердите действие',
  },
  'th-TH': {
    cancel: 'ยกเลิก', collapse: 'ย่อ', confirm: 'ยืนยัน', expand: 'ขยาย',
    prompt: 'แจ้งเตือน', reset: 'รีเซ็ต', submit: 'ส่ง', confirmTitle: 'โปรดยืนยัน',
  },
  'vi-VN': {
    cancel: 'Hủy', collapse: 'Thu gọn', confirm: 'Xác nhận', expand: 'Mở rộng',
    prompt: 'Thông báo', reset: 'Đặt lại', submit: 'Gửi', confirmTitle: 'Vui lòng xác nhận',
  },
  'zh-CN': {
    cancel: '取消',
    collapse: '收起',
    confirm: '确认',
    expand: '展开',
    prompt: '提示',
    reset: '重置',
    submit: '提交',
    confirmTitle: '请确认',
  },
  'zh-TW': {
    cancel: '取消', collapse: '收起', confirm: '確認', expand: '展開',
    prompt: '提示', reset: '重設', submit: '提交', confirmTitle: '請確認',
  },
};

export const getMessages = (locale: Locale) => messages[locale];
