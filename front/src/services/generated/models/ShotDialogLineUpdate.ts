/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DialogueLineMode } from './DialogueLineMode';
export type ShotDialogLineUpdate = {
    index?: (number | null);
    text?: (string | null);
    line_mode?: (DialogueLineMode | null);
    speaker_character_id?: (string | null);
    target_character_id?: (string | null);
    speaker_name?: (string | null);
    target_name?: (string | null);
    tts_voice_id?: (string | null);
    tts_audio_file_id?: (string | null);
    start_time_ms?: (number | null);
    end_time_ms?: (number | null);
};

