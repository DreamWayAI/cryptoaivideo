// N8N Workflow для обработки больших видео
// Этот код используется в Function или Code node в n8n

const axios = require('axios');
const FormData = require('form-data');

// Конфигурация
const UPLOAD_SERVER_URL = process.env.UPLOAD_SERVER_URL || 'https://your-railway-app.up.railway.app';
const TELEGRAM_CHAT_ID = $node["Telegram Trigger"].json["chat"]["id"];
const TELEGRAM_USER_ID = $node["Telegram Trigger"].json["from"]["id"];
const TELEGRAM_FILE = $node["Telegram Trigger"].json["video"] || $node["Telegram Trigger"].json["document"];

// Функция для обработки видео
async function processLargeVideo() {
    try {
        // 1. Для больших файлов - генерируем presigned URL
        if (TELEGRAM_FILE.file_size > 50 * 1024 * 1024) { // > 50MB
            
            // Генерируем URL для прямой загрузки
            const presignedResponse = await axios.post(
                `${UPLOAD_SERVER_URL}/generate-upload-url`,
                {
                    file_name: TELEGRAM_FILE.file_name || 'video.mp4',
                    file_type: TELEGRAM_FILE.mime_type || 'video/mp4',
                    user_id: TELEGRAM_USER_ID.toString(),
                    expires_in: 3600
                }
            );
            
            const uploadUrl = presignedResponse.data.upload_url;
            const s3Key = presignedResponse.data.s3_key;
            
            // 2. Информируем пользователя о способе загрузки
            await $send.telegram({
                chat_id: TELEGRAM_CHAT_ID,
                text: `📤 Для загрузки большого файла (${(TELEGRAM_FILE.file_size / (1024*1024)).toFixed(2)} MB) используйте эту ссылку:\n\n${uploadUrl}\n\nСсылка действительна 1 час.`,
                parse_mode: 'HTML'
            });
            
            // 3. Запускаем фоновую обработку через сервер
            const uploadResponse = await axios.post(
                `${UPLOAD_SERVER_URL}/upload-telegram-file`,
                {
                    file_id: TELEGRAM_FILE.file_id,
                    file_name: TELEGRAM_FILE.file_name || 'video.mp4',
                    user_id: TELEGRAM_USER_ID.toString(),
                    chat_id: TELEGRAM_CHAT_ID.toString(),
                    file_size: TELEGRAM_FILE.file_size
                }
            );
            
            // 4. Если файл обрабатывается в фоне, сохраняем job_id
            if (uploadResponse.data.status === 'processing') {
                const jobId = uploadResponse.data.job_id;
                
                // Сохраняем в базу данных или Redis для отслеживания
                await $store.set(`job_${TELEGRAM_USER_ID}`, {
                    jobId: jobId,
                    fileName: TELEGRAM_FILE.file_name,
                    status: 'processing',
                    createdAt: new Date().toISOString()
                });
                
                // Уведомляем пользователя
                await $send.telegram({
                    chat_id: TELEGRAM_CHAT_ID,
                    text: `⏳ Ваше видео обрабатывается в фоновом режиме.\nID задачи: <code>${jobId}</code>\n\nВы получите уведомление, когда обработка завершится.`,
                    parse_mode: 'HTML'
                });
            }
            
            return {
                success: true,
                jobId: uploadResponse.data.job_id,
                status: uploadResponse.data.status
            };
            
        } else {
            // Для маленьких файлов - прямая загрузка
            const uploadResponse = await axios.post(
                `${UPLOAD_SERVER_URL}/upload-telegram-file`,
                {
                    file_id: TELEGRAM_FILE.file_id,
                    file_name: TELEGRAM_FILE.file_name || 'video.mp4',
                    user_id: TELEGRAM_USER_ID.toString(),
                    chat_id: TELEGRAM_CHAT_ID.toString(),
                    file_size: TELEGRAM_FILE.file_size
                }
            );
            
            if (uploadResponse.data.status === 'completed') {
                const s3Url = uploadResponse.data.s3_url;
                
                // Запускаем обработку через Vizard
                const vizardResponse = await axios.post(
                    `${UPLOAD_SERVER_URL}/initiate-vizard-processing`,
                    new URLSearchParams({
                        s3_url: s3Url,
                        user_id: TELEGRAM_USER_ID.toString(),
                        chat_id: TELEGRAM_CHAT_ID.toString(),
                        vizard_settings: JSON.stringify({
                            clips: 10,
                            duration: 60,
                            format: 'vertical',
                            auto_captions: true
                        })
                    }),
                    {
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded'
                        }
                    }
                );
                
                await $send.telegram({
                    chat_id: TELEGRAM_CHAT_ID,
                    text: `✅ Видео загружено!\n🎬 Начинаю нарезку через Vizard...\n\nJob ID: <code>${vizardResponse.data.job_id}</code>`,
                    parse_mode: 'HTML'
                });
                
                return {
                    success: true,
                    s3Url: s3Url,
                    vizardJobId: vizardResponse.data.job_id
                };
            }
        }
        
    } catch (error) {
        console.error('Error processing video:', error);
        
        // Отправляем сообщение об ошибке пользователю
        await $send.telegram({
            chat_id: TELEGRAM_CHAT_ID,
            text: `❌ Произошла ошибка при обработке видео:\n${error.message}\n\nПопробуйте еще раз или обратитесь в поддержку.`,
            parse_mode: 'HTML'
        });
        
        throw error;
    }
}

// Функция для проверки статуса задачи
async function checkJobStatus(jobId) {
    try {
        const response = await axios.get(`${UPLOAD_SERVER_URL}/status/${jobId}`);
        return response.data;
    } catch (error) {
        if (error.response?.status === 404) {
            return { status: 'not_found' };
        }
        throw error;
    }
}

// Функция для обработки webhook от Vizard
async function handleVizardWebhook(data) {
    const { job_id, status, result } = data;
    
    if (status === 'completed') {
        // Получаем информацию о пользователе из Redis/DB
        const jobInfo = await $store.get(`vizard_job_${job_id}`);
        
        if (jobInfo) {
            // Отправляем результаты пользователю
            const message = `✅ Обработка завершена!\n\nРезультаты:\n`;
            const clips = result.clips.map((clip, index) => 
                `${index + 1}. <a href="${clip.url}">Клип ${index + 1}</a> (${clip.duration}s)`
            ).join('\n');
            
            await $send.telegram({
                chat_id: jobInfo.chat_id,
                text: message + clips,
                parse_mode: 'HTML'
            });
            
            // Автопостинг в социальные сети
            if (jobInfo.auto_post) {
                await autoPostToSocialMedia(result.clips, jobInfo);
            }
        }
    }
}

// Функция для автопостинга в соцсети
async function autoPostToSocialMedia(clips, settings) {
    const socialNetworks = settings.social_networks || ['instagram', 'tiktok', 'youtube_shorts'];
    
    for (const network of socialNetworks) {
        for (const [index, clip] of clips.entries()) {
            try {
                // Здесь вызываем соответствующие API для постинга
                switch(network) {
                    case 'instagram':
                        // Instagram API posting
                        break;
                    case 'tiktok':
                        // TikTok API posting
                        break;
                    case 'youtube_shorts':
                        // YouTube Shorts API posting
                        break;
                }
                
                // Задержка между постами
                await new Promise(resolve => setTimeout(resolve, 5000));
                
            } catch (error) {
                console.error(`Failed to post to ${network}:`, error);
            }
        }
    }
}

// Экспорт для использования в n8n
return {
    processLargeVideo,
    checkJobStatus,
    handleVizardWebhook,
    autoPostToSocialMedia
};
