export type RStats = {
  meta: {
    format: 2,
    time_data: string,
    time_script: string
  },
  daily: [
    {
      date: string,
      traffic: [down: number, up: number],
      error: [down: boolean, up: boolean]
      misc?: {
        [key: string]: any
      }
    }
  ],
  monthly: [
    {
      date: string,
      traffic: [down: number, up: number],
      error: [down: boolean, up: boolean]
      misc?: {
        [key: string]: any
      }
    }
  ]
}

export type RStatsLegacyV1 = {
  meta: {
    time_data: string,
    time_script: string
  },
  daily: [
    {
      date: string,
      down: number,
      up: number,
      comment?: {
        message: string,
        error_down: boolean,
        error_up: boolean
      }
    }
  ],
  monthly: [
    {
      date: string,
      down: number,
      up: number,
      comment?: {
        message: string
      }
    }
  ]
}