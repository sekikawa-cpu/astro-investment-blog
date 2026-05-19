/**
 * Cloudflare Pages Function: POST /api/contact
 * 環境変数 RESEND_API_KEY を Cloudflare Pages の設定に追加してください。
 */
export async function onRequestPost(context) {
  try {
    const formData = await context.request.formData();
    const name    = (formData.get('name')    || '').trim();
    const email   = (formData.get('email')   || '').trim();
    const subject = (formData.get('subject') || 'お問い合わせ').trim();
    const message = (formData.get('message') || '').trim();

    if (!name || !email || !message) {
      return Response.json({ error: '必須項目を入力してください。' }, { status: 400 });
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return Response.json({ error: 'メールアドレスの形式が正しくありません。' }, { status: 400 });
    }

    const RESEND_API_KEY = context.env.RESEND_API_KEY;
    if (!RESEND_API_KEY) {
      console.error('RESEND_API_KEY is not set');
      return Response.json({ error: 'メール送信の設定が完了していません。' }, { status: 500 });
    }

    const safeMsg = message.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${RESEND_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from: 'お問い合わせフォーム <noreply@tech-wealth-mind.com>',
        to: ['sekijun0301@gmail.com'],
        reply_to: email,
        subject: `[お問い合わせ] ${subject}`,
        text: `お名前: ${name}\nメールアドレス: ${email}\n件名: ${subject}\n\nメッセージ:\n${message}`,
        html: `
          <p><strong>お名前:</strong> ${name}</p>
          <p><strong>返信先:</strong> <a href="mailto:${email}">${email}</a></p>
          <p><strong>件名:</strong> ${subject}</p>
          <hr />
          <p><strong>メッセージ:</strong></p>
          <p style="white-space:pre-wrap;background:#f8fafc;padding:1rem;border-radius:6px;">${safeMsg}</p>
          <hr />
          <p style="color:#64748b;font-size:0.8rem;">会社員の生活日記 お問い合わせフォームより送信</p>
        `,
      }),
    });

    if (res.ok) {
      return Response.json({ success: true });
    }
    const err = await res.json().catch(() => ({}));
    console.error('Resend API error:', JSON.stringify(err));
    return Response.json({ error: '送信に失敗しました。時間をおいて再度お試しください。' }, { status: 500 });

  } catch (e) {
    console.error('Contact function error:', e);
    return Response.json({ error: '送信に失敗しました。時間をおいて再度お試しください。' }, { status: 500 });
  }
}
